function buildPageItems(page, totalPages) {
  const current = Math.max(1, Number(page) || 1);
  const total = Math.max(1, Number(totalPages) || 1);
  const items = new Set([1, total, current, current - 1, current + 1]);
  if (current <= 3) {
    items.add(2);
    items.add(3);
  }
  if (current >= total - 2) {
    items.add(total - 1);
    items.add(total - 2);
  }

  const ordered = [...items].filter((item) => item >= 1 && item <= total).sort((a, b) => a - b);
  return ordered.reduce((result, item) => {
    const previous = result[result.length - 1];
    if (typeof previous === 'number' && item - previous > 1) {
      result.push(`ellipsis-${previous}-${item}`);
    }
    result.push(item);
    return result;
  }, []);
}

export default function Pagination({ page, totalPages, onPageChange }) {
  const current = Math.max(1, Number(page) || 1);
  const total = Math.max(1, Number(totalPages) || 1);
  if (total <= 1) return null;

  const pageItems = buildPageItems(current, total);

  return (
    <nav className="pagination-bar" aria-label="Phân trang">
      <button
        type="button"
        className="pagination-button"
        onClick={() => onPageChange?.(current - 1)}
        disabled={current <= 1}
      >
        Trước
      </button>
      {pageItems.map((item) => (
        typeof item === 'number' ? (
          <button
            key={item}
            type="button"
            className={`pagination-page ${item === current ? 'active' : ''}`}
            onClick={() => onPageChange?.(item)}
            aria-current={item === current ? 'page' : undefined}
          >
            {item}
          </button>
        ) : (
          <span key={item} className="pagination-ellipsis">...</span>
        )
      ))}
      <button
        type="button"
        className="pagination-button"
        onClick={() => onPageChange?.(current + 1)}
        disabled={current >= total}
      >
        Sau
      </button>
    </nav>
  );
}
