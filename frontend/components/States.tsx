export function LoadingPanel() {
  return (
    <div className="loading-panel">
      <span className="spinner" />
      Loading paper state…
    </div>
  );
}

export function ErrorPanel({
  error,
  onRetry,
}: {
  error: string;
  onRetry?: () => void;
}) {
  return (
    <div className="error-panel">
      <strong>Dashboard data is unavailable.</strong>
      <p>{error}</p>
      {onRetry ? (
        <button className="button" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
