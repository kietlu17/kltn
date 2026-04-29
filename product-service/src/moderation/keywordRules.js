const BLOCKED_KEYWORDS = [
  'vu khi',
  'sung',
  'dan duoc',
  'bom',
  'dao gam',
  'hang gia',
  'fake',
  'replica',
  'nhai thuong hieu',
  'ma tuy',
  'can sa',
  'thuoc lac',
  'giay to gia',
  'cccd gia',
  'ho chieu gia'
];

function normalizeText(value) {
  return String(value || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function compactText(value) {
  return normalizeText(value).replace(/\s+/g, '');
}

function evaluateProductContent(payload) {
  const raw = [payload?.name, payload?.description, payload?.detail].filter(Boolean).join(' ');
  const normalized = normalizeText(raw);
  const compact = compactText(raw);

  const matches = [];
  BLOCKED_KEYWORDS.forEach((keyword) => {
    const normalizedKeyword = normalizeText(keyword);
    const compactKeyword = compactText(keyword);
    if (!normalizedKeyword) return;
    if (normalized.includes(normalizedKeyword) || compact.includes(compactKeyword)) {
      matches.push(keyword);
    }
  });

  return {
    flagged: matches.length > 0,
    matches
  };
}

module.exports = { evaluateProductContent };
