/** The server's explanation of a failed request (FastAPI `detail`), as one readable string. */
export const errorDetail = (err: unknown, fallback = 'Something went wrong. Please try again.'): string => {
  const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (typeof d?.msg === 'string' ? d.msg : JSON.stringify(d))).join('; ');
  }
  return fallback;
};
