import type { InterviewListItem, ReviewStatus } from '../types/interview';

export type SortKey = 'name' | 'date' | 'needsReview' | 'adopted';
export interface SortRule {
  key: SortKey;
  descending: boolean;
}
export interface CandidateFilter {
  search: string;
  review: 'all' | ReviewStatus;
  summary: string;
}

export function candidateRows(
  items: readonly InterviewListItem[],
  filter: CandidateFilter,
  sort: readonly SortRule[],
) {
  const search = filter.search.normalize('NFC').trim().toLocaleLowerCase('ko-KR');
  const rows = items.filter(
    (item) =>
      (!search ||
        (item.candidateName ?? '').normalize('NFC').toLocaleLowerCase('ko-KR').includes(search)) &&
      (filter.review === 'all' || item.reviewStatus === filter.review) &&
      (filter.summary === 'all' || item.summaryStatus === filter.summary),
  );
  return rows.sort((a, b) => {
    for (const rule of sort) {
      let value: number;
      if (rule.key === 'name')
        value = (a.candidateName ?? '').localeCompare(b.candidateName ?? '', 'ko-KR');
      else {
        const left =
          rule.key === 'date'
            ? a.interviewedAt
              ? Date.parse(a.interviewedAt)
              : null
            : (a.counts?.[rule.key] ?? null);
        const right =
          rule.key === 'date'
            ? b.interviewedAt
              ? Date.parse(b.interviewedAt)
              : null
            : (b.counts?.[rule.key] ?? null);
        if (left === null && right !== null) return 1;
        if (left !== null && right === null) return -1;
        value = (left ?? 0) - (right ?? 0);
      }
      if (value) return rule.descending ? -value : value;
    }
    return 0;
  });
}

export function rangeSelection(
  ids: readonly string[],
  anchor: string | null,
  target: string,
  selected: ReadonlySet<string>,
  checked: boolean,
): Set<string> {
  const next = new Set(selected);
  const end = ids.indexOf(target);
  const start = anchor ? ids.indexOf(anchor) : -1;
  const range =
    start < 0 || end < 0 ? [target] : ids.slice(Math.min(start, end), Math.max(start, end) + 1);
  for (const id of range) {
    if (checked) next.add(id);
    else next.delete(id);
  }
  return next;
}

/** 표를 외부 도구에 붙여넣어도 사용자 문자열이 수식으로 실행되지 않게 한다. */
export function delimitedCell(value: unknown, delimiter = ','): string {
  let text = value === null || value === undefined ? '' : String(value);
  if (/^[\s]*[=+@-]/.test(text)) text = `'${text}`;
  return text.includes(delimiter) || /["\r\n]/.test(text)
    ? `"${text.replaceAll('"', '""')}"`
    : text;
}

export function saveDownload(content: Blob, name: string) {
  const url = URL.createObjectURL(content);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
