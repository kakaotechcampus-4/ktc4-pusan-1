export type MemoSaveState = 'idle' | 'saving' | 'saved' | 'failed';
export interface MemoDraft {
  memo: string;
  state: MemoSaveState;
  version: number;
  saved: number;
  hydrated: boolean;
}

/** 면접별 요청을 직렬화하고 화면을 닫아도 미저장 입력을 남긴다. */
export function createMemoQueue(write: (id: string, memo: string) => Promise<unknown>) {
  const drafts = new Map<string, MemoDraft>();
  const listeners = new Set<() => void>();
  const running = new Map<string, Promise<void>>();
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const emit = () => listeners.forEach((listener) => listener());
  const read = (id: string): MemoDraft => {
    if (!drafts.has(id))
      drafts.set(id, { memo: '', state: 'idle', version: 0, saved: 0, hydrated: false });
    return drafts.get(id)!;
  };
  const flush = (id: string): Promise<void> => {
    clearTimeout(timers.get(id));
    if (running.has(id)) return running.get(id)!;
    const first = drafts.get(id);
    if (!first || first.version === first.saved) return Promise.resolve();
    const task = (async () => {
      while (drafts.has(id)) {
        const current = read(id);
        if (current.version === current.saved) break;
        const { memo, version } = current;
        drafts.set(id, { ...current, state: 'saving' });
        emit();
        try {
          await write(id, memo);
          if (!drafts.has(id)) break;
          const next = read(id);
          drafts.set(id, {
            ...next,
            saved: version,
            state: next.version === version ? 'saved' : 'saving',
          });
          emit();
        } catch {
          if (drafts.has(id)) {
            drafts.set(id, { ...read(id), state: 'failed' });
            emit();
          }
          break;
        }
      }
    })().finally(() => running.delete(id));
    running.set(id, task);
    return task;
  };
  return {
    read,
    hydrate(id: string, memo: string) {
      const current = read(id);
      if (!current.hydrated && current.version === current.saved) {
        drafts.set(id, { ...current, memo, hydrated: true });
        emit();
      }
    },
    edit(id: string, value: string) {
      const current = read(id);
      drafts.set(id, {
        ...current,
        memo: value.replaceAll('\0', '').slice(0, 4000),
        version: current.version + 1,
        state: 'idle',
      });
      clearTimeout(timers.get(id));
      timers.set(
        id,
        setTimeout(() => void flush(id), 800),
      );
      emit();
    },
    flush,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    clear() {
      timers.forEach(clearTimeout);
      timers.clear();
      drafts.clear();
      emit();
    },
  };
}
