/*
 * Platform category taxonomy: Chủng loại -> Chủng loại con -> ... -> Sản phẩm.
 *
 * Importers used to create flat, source-prefixed names ("YODY · Áo thun nữ",
 * "MUJI · Quần áo › Trang Phục Nữ › Áo Thun › 053:L&S T-SHIRT", "Laptop").
 * canonicalPath() maps such a name onto one shared tree; ensureCategoryPath()
 * creates the missing ancestors. Shared ancestors are platform nodes
 * (shopId = PLATFORM_SHOP_ID); a seller's own categories stay the seller's,
 * so products keep their categoryId and the shop ownership checks still hold.
 */

const PLATFORM_SHOP_ID = 'platform';
const SEPARATOR = ' › ';

const ROOTS = {
  fashion: 'Thời trang',
  electronics: 'Điện tử',
  home: 'Nhà cửa & Đời sống',
  beauty: 'Làm đẹp',
  food: 'Thực phẩm',
  books: 'Sách',
  other: 'Khác'
};

const AUDIENCES = [
  { label: 'Trẻ em', pattern: /(^|\s)(trẻ em|bé trai|bé gái|kid|kids)(?=\s|$)/i },
  { label: 'Nữ', pattern: /(^|\s)(nữ|women)(?=\s|$)/i },
  { label: 'Nam', pattern: /(^|\s)(nam|men)(?=\s|$)/i }
];

// Single-level names are classified by keywords on accent-free text, so
// seller-typed names ("ban phim", "pc", "Tai Nghe Có Dây") are recognised.
// First match wins: books and electronics before the audience words of fashion.
const KEYWORDS = [
  [ROOTS.books, /(^|\s)(sach|books?|fiction|literature|literary|novel|truyen tranh|tieu thuyet|thriller|mystery|picture books?|teaching|learning|kinh doanh|giao trinh)(\s|$)/],
  [ROOTS.electronics, /(^|\s)(laptop|pc|may tinh|may vi tinh|linh kien|ban phim|chuot may tinh|tai nghe|loa|dien thoai|smartphone|tablet|may tinh bang|dong ho thong minh|smartwatch|may anh|camera|tivi|man hinh|sac du phong|thiet bi so|phu kien so|phu kien cong nghe|cong nghe)(\s|$)/],
  [ROOTS.beauty, /(^|\s)(lam dep|my pham|cham soc da|cham soc toc|duong da|trang diem|son|ban chai|kem danh rang|suc khoe)(\s|$)/],
  [ROOTS.food, /(^|\s)(thuc pham|do an|do uong|banh|keo|tra|ca phe)(\s|$)/],
  [ROOTS.home, /(^|\s)(nha cua|doi song|gia dung|noi that|nha bep|van phong pham)(\s|$)/]
];
const FASHION = /^(ao|quan|dam|vay|chan vay|do bo|do lot|giay|dep|tui|balo|vali|tat|vo|mu|non|khan|that lung|thoi trang|phu kien thoi trang)(\s|$)/;

function fold(value) {
  return clean(value)
    .toLocaleLowerCase('vi')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/đ/g, 'd')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

// MUJI-style multi-level paths: source root -> platform root, and second-level
// labels that name an audience or move to another branch.
const SOURCE_ROOTS = {
  'quan ao': ROOTS.fashion,
  'thoi trang': ROOTS.fashion,
  'nha cua doi song': ROOTS.home,
  'nha cua': ROOTS.home,
  'lam dep': ROOTS.beauty,
  'thuc pham': ROOTS.food,
  'dien tu': ROOTS.electronics,
  'sach': ROOTS.books
};
const SECOND_LEVEL = {
  'trang phục nam': 'Nam',
  'trang phục nữ': 'Nữ',
  'trang phục trẻ em': 'Trẻ em',
  'phụ kiện': 'Phụ kiện'
};

function clean(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function key(value) {
  return clean(value).toLocaleLowerCase('vi');
}

function stripSource(name) {
  // "MUJI · ...", "YODY · ...": the merchant, not a browse level.
  return clean(name).replace(/^.{1,48}?\s*[·•]\s*/, '');
}

function cleanSegment(segment) {
  // "053:L&S T-SHIRT" is a merchant line code, not part of the label.
  return clean(String(segment).replace(/^\d{1,4}\s*:\s*/, ''));
}

function splitPath(name) {
  return stripSource(name)
    .split(/\s*(?:›|>|»|→)\s*/)
    .map(cleanSegment)
    .filter(Boolean);
}

function capitalize(value) {
  const text = clean(value);
  return text ? text.charAt(0).toLocaleUpperCase('vi') + text.slice(1) : text;
}

function audienceOf(name) {
  return AUDIENCES.find(({ pattern }) => pattern.test(name)) || null;
}

/**
 * The canonical path of a category name, root first.
 *   "YODY · Áo thun nữ"                          -> [Thời trang, Nữ, Áo thun nữ]
 *   "MUJI · Quần áo › Trang Phục Nữ › Áo Thun"    -> [Thời trang, Nữ, Áo Thun]
 *   "MUJI · Nhà Cửa Đời Sống › Đồ Điện Tử › Quạt" -> [Điện tử, Đồ điện gia dụng, Quạt]
 *   "Laptop"                                      -> [Điện tử, Laptop]
 *   "Thời trang nam"                              -> [Thời trang, Nam]
 */
function canonicalPath(rawName) {
  const segments = mapPath(rawName);
  // Roots are shared platform nodes: a seller category that names a whole
  // root ("MUJI · Quần áo") holds that root's general items.
  return segments.length === 1 && Object.values(ROOTS).includes(segments[0])
    ? [segments[0], 'Tổng hợp']
    : segments;
}

function mapPath(rawName) {
  const parts = splitPath(rawName);
  if (!parts.length) return [];
  if (parts.length > 1) {
    const root = SOURCE_ROOTS[fold(parts[0])];
    if (!root) return parts.map(capitalize);
    let rest = parts.slice(1);
    if (root === ROOTS.home && rest.length && key(rest[0]) === 'đồ điện tử') {
      return [ROOTS.electronics, 'Đồ điện gia dụng', ...rest.slice(1)];
    }
    if (rest.length && SECOND_LEVEL[key(rest[0])]) {
      rest = [SECOND_LEVEL[key(rest[0])], ...rest.slice(1)];
    }
    return [root, ...rest];
  }
  const [name] = parts;
  const lowered = key(name);
  const folded = fold(name);
  if (SOURCE_ROOTS[folded]) return [SOURCE_ROOTS[folded]];
  if (folded === 'san pham khac' || folded === 'khac') return [ROOTS.other, capitalize(name)];
  for (const [root, pattern] of KEYWORDS) {
    if (pattern.test(folded)) return [root, label(name)];
  }
  const audience = audienceOf(lowered);
  if (audience) {
    const base = clean(lowered.replace(audience.pattern, ' '));
    // "Nam", "Thời trang nữ": the category is the audience branch itself.
    if (!base || fold(base) === 'thoi trang') return [ROOTS.fashion, audience.label];
    return [ROOTS.fashion, audience.label, capitalize(name)];
  }
  if (FASHION.test(folded)) return [ROOTS.fashion, capitalize(name)];
  return [ROOTS.other, capitalize(name)];
}

function label(name) {
  // Short seller-typed codes read as acronyms: "pc" -> "PC".
  const text = clean(name);
  return text.length <= 3 ? text.toUpperCase() : capitalize(text);
}

function joinPath(segments) {
  return segments.map(clean).filter(Boolean).join(SEPARATOR);
}

/**
 * Find or create every level of `segments`. Intermediate levels reuse the
 * shop's own category at that position when it has one, otherwise a
 * platform node; the last level is always the shop's category.
 */
async function ensureCategoryPath(Category, segments, shopId, { description = '' } = {}) {
  let parent = null;
  for (let index = 0; index < segments.length; index += 1) {
    const name = segments[index];
    const last = index === segments.length - 1;
    const parentId = parent ? String(parent._id) : null;
    const path = joinPath(segments.slice(0, index + 1));
    const fields = { $set: { path, level: index }, $setOnInsert: { description: last ? description : '' } };
    // Roots are always platform nodes, so every shop shares the same top level.
    const owner = last && index > 0 ? shopId : PLATFORM_SHOP_ID;
    let node = last || index === 0 ? null : await Category.findOne({ shopId, parentId, name });
    if (!node) {
      node = await Category.findOneAndUpdate(
        { shopId: owner, parentId, name },
        fields,
        { upsert: true, new: true, setDefaultsOnInsert: true }
      );
    }
    parent = node;
  }
  return parent;
}

/** Ids of a category and all of its descendants. */
async function descendantIds(Category, categoryId) {
  const ids = [String(categoryId)];
  const seen = new Set(ids);
  for (let cursor = 0; cursor < ids.length && ids.length < 5000; cursor += 1) {
    const children = await Category.find({ parentId: ids[cursor] }, { _id: 1 }).lean();
    for (const child of children) {
      const id = String(child._id);
      if (!seen.has(id)) {
        seen.add(id);
        ids.push(id);
      }
    }
  }
  return ids;
}

/** Display path and depth of a category placed under `parentId`. */
async function pathFields(Category, name, parentId) {
  if (!parentId) return { parentId: null, path: clean(name), level: 0 };
  const parent = await Category.findById(parentId).lean();
  if (!parent) return null;
  const parentPath = parent.path || parent.name;
  return {
    parentId: String(parent._id),
    path: joinPath([parentPath, name]),
    level: Number(parent.level || 0) + 1
  };
}

/** Recompute path and level below a renamed or moved category. */
async function refreshDescendantPaths(Category, categoryId) {
  const queue = [await Category.findById(categoryId).lean()].filter(Boolean);
  for (let cursor = 0; cursor < queue.length && cursor < 5000; cursor += 1) {
    const parent = queue[cursor];
    const children = await Category.find({ parentId: String(parent._id) }).lean();
    for (const child of children) {
      const path = joinPath([parent.path || parent.name, child.name]);
      const level = Number(parent.level || 0) + 1;
      await Category.updateOne({ _id: child._id }, { $set: { path, level } });
      queue.push({ ...child, path, level });
    }
  }
}

module.exports = {
  PLATFORM_SHOP_ID,
  refreshDescendantPaths,
  ROOTS,
  SEPARATOR,
  canonicalPath,
  descendantIds,
  ensureCategoryPath,
  joinPath,
  pathFields
};
