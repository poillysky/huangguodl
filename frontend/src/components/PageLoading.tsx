export default function PageLoading({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <div className="page-loading" role="status" aria-live="polite" aria-busy="true">
      <span className="page-loading__spin" aria-hidden />
      <span className="page-loading__text">加载中</span>
    </div>
  );
}
