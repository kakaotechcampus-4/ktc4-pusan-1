import { Link, useParams } from 'react-router-dom';
import { ReportPanel } from '../components/review/ReportPanel';

export default function InterviewReportPage() {
  const { interviewId } = useParams<{ interviewId: string }>();
  if (!interviewId) return null;
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6">
      <Link to={`/review/${interviewId}`} className="text-brand mb-6 inline-block text-sm">
        ← 면접 기록
      </Link>
      <ReportPanel interviewId={interviewId} />
    </div>
  );
}
