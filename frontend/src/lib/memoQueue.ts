export type MemoSaveState = 'idle' | 'saving' | 'saved' | 'failed' | 'conflict';
export interface MemoDraft<T = unknown> {
  memo: string;
  state: MemoSaveState;
  version: number;
  saved: number;
  hydrated: boolean;
  baseline: string;
  serverMemo?: string;
  result?: T;
}

/** 면접별 요청을 직렬화하고 화면을 닫아도 미저장 입력을 남긴다. */
export function createMemoQueue<T>(
  write: (id: string, memo: string, expectedMemo: string) => Promise<T>,
) {
  const drafts = new Map<string, MemoDraft<T>>();
  const listeners = new Set<() => void>();
  const running = new Map<string, Promise<void>>();
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  let epoch = 0;
  const emit = () => listeners.forEach((listener) => listener());
  const read = (id: string): MemoDraft<T> => {
    if (!drafts.has(id))
      drafts.set(id, {
        memo: '',
        state: 'idle',
        version: 0,
        saved: 0,
        hydrated: false,
        baseline: '',
      });
    return drafts.get(id)!;
  };
  const flush = (id: string): Promise<void> => {
    clearTimeout(timers.get(id));
    if (running.has(id)) return running.get(id)!;
    const first = drafts.get(id);
    if (!first || first.state === 'conflict' || first.version === first.saved)
      return Promise.resolve();
    const started = epoch;
    const task = (async () => {
      while (drafts.has(id) && epoch === started) {
        const current = read(id);
        if (current.version === current.saved) break;
        const { memo, version, baseline } = current;
        drafts.set(id, { ...current, state: 'saving' });
        emit();
        try {
          const result = await write(id, memo, baseline);
          if (!drafts.has(id) || epoch !== started) break;
          const next = read(id);
          drafts.set(id, {
            ...next,
            saved: version,
            baseline: memo,
            serverMemo: undefined,
            result,
            state: next.version === version ? 'saved' : 'saving',
          });
          emit();
        } catch (error) {
          if (drafts.has(id) && epoch === started) {
            drafts.set(id, {
              ...read(id),
              state: (error as { code?: string })?.code === 'MEMO_CONFLICT' ? 'conflict' : 'failed',
              serverMemo: undefined,
            });
            emit();
          }
          break;
        }
      }
    })().finally(() => {
      if (running.get(id) === task) running.delete(id);
    });
    running.set(id, task);
    return task;
  };
  return {
    read,
    hydrate(id: string, memo: string) {
      const current = read(id);
      if (!current.hydrated && current.version === current.saved) {
        drafts.set(id, { ...current, memo, baseline: memo, hydrated: true });
        emit();
      }
    },
    edit(id: string, value: string) {
      const current = read(id);
      drafts.set(id, {
        ...current,
        memo: value.replaceAll('\0', '').slice(0, 4000),
        version: current.version + 1,
        state: current.state === 'conflict' ? 'conflict' : 'idle',
      });
      clearTimeout(timers.get(id));
      if (current.state !== 'conflict')
        timers.set(
          id,
          setTimeout(() => void flush(id), 800),
        );
      emit();
    },
    restoreDraft(id: string, memo: string) {
      const current = read(id);
      if (current.version !== current.saved) return;
      clearTimeout(timers.get(id));
      drafts.set(id, {
        ...current,
        memo,
        version: current.version + 1,
        state: 'conflict',
        serverMemo: undefined,
      });
      emit();
    },
    reviewConflict(id: string, serverMemo: string) {
      const current = read(id);
      if (current.state !== 'conflict') return;
      drafts.set(id, { ...current, serverMemo });
      emit();
    },
    reapply(id: string) {
      const current = read(id);
      if (current.state !== 'conflict' || current.serverMemo === undefined)
        return Promise.resolve();
      drafts.set(id, {
        ...current,
        baseline: current.serverMemo,
        state: 'idle',
        serverMemo: undefined,
      });
      return flush(id);
    },
    flush,
    async flushForRead(ids: readonly string[]) {
      const started = epoch;
      for (const id of ids) {
        await flush(id);
        if (started !== epoch) throw new Error('로그인 상태가 바뀌었습니다.');
        const draft = drafts.get(id);
        if (draft && draft.version !== draft.saved)
          throw new Error('메모를 저장하지 못했습니다. 저장 후 다시 시도해 주세요.');
      }
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    clear() {
      epoch += 1;
      running.clear();
      timers.forEach(clearTimeout);
      timers.clear();
      drafts.clear();
      emit();
    },
  };
}
