function decodeEntity(match, entity) {
  const named = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
  const key = entity.toLowerCase();
  if (Object.prototype.hasOwnProperty.call(named, key)) return named[key];
  if (key.startsWith('#')) {
    const hex = key.startsWith('#x');
    const codePoint = Number.parseInt(key.slice(hex ? 2 : 1), hex ? 16 : 10);
    if (Number.isInteger(codePoint) && codePoint >= 0 && codePoint <= 0x10ffff) {
      return String.fromCodePoint(codePoint);
    }
  }
  return match;
}

function htmlToPlainText(value, omitLines = []) {
  const omitted = new Set(omitLines.map((line) => String(line || '').replace(/\s+/g, ' ').trim()));
  return String(value || '')
    .replace(/<br\s*\/?\s*>/gi, '\n')
    .replace(/<\s*\/\s*(?:h[1-6]|p|li|ul|ol|section)\s*>/gi, '\n')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&(#(?:x[0-9a-f]+|\d+)|[a-z]+);/gi, decodeEntity)
    .split('\n')
    .map((line) => line.replace(/\s+/g, ' ').trim())
    .filter((line) => line && !omitted.has(line))
    .join('\n');
}

module.exports = { htmlToPlainText };
