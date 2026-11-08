/** Bounded independent checks; on failure drain owned work before rejecting. */
export async function mapLimit(items, limit, operation) {
  if (!Number.isInteger(limit) || limit < 1 || limit > 8) throw new Error('Invalid verification concurrency');
  let next = 0, failed = false, firstError;
  const results = new Array(items.length);
  async function worker() {
    while (!failed && next < items.length) {
      const index = next++;
      try { results[index] = await operation(items[index], index); }
      catch (error) { if (!failed) firstError = error; failed = true; }
    }
  }
  await Promise.all(Array.from({length: Math.min(items.length, limit)}, worker));
  if (failed) throw firstError;
  return results;
}
