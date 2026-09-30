/* Import a small, idempotent Tiki fashion sample with original Vietnamese copy. */
const mongoose = require('mongoose');
const { connectMongo } = require('../config/db');
const Product = require('../models/Product');
const Category = require('../models/Category');
const { initProducer, closeProducer, publishProductCreated } = require('../kafka/producer');

const APPLY = process.argv.includes('--apply');
const TARGET_PER_AUDIENCE = Number(process.env.TIKI_IMPORT_PER_AUDIENCE || 25);
const SHOP_ID = process.env.TIKI_IMPORT_SHOP_ID || '69f1b1cb00f071907a7e0fd4';
const USER_AGENT = 'Mozilla/5.0 (compatible; EcommerceCatalogImporter/1.0)';
const SOURCES = [
  { audience: 'nam', categoryId: 915, categoryName: 'Thời trang nam', urlKey: 'thoi-trang-nam' },
  { audience: 'nữ', categoryId: 931, categoryName: 'Thời trang nữ', urlKey: 'thoi-trang-nu' }
];

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function plainText(value) {
  return String(value || '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;|&#160;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/\s+/g, ' ')
    .trim();
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function productKind(name) {
  const text = name.toLocaleLowerCase('vi');
  const kinds = ['áo sơ mi', 'áo polo', 'áo thun', 'áo khoác', 'áo len', 'quần tây', 'quần jeans',
    'quần jean', 'quần short', 'quần ống rộng', 'chân váy', 'đầm', 'váy', 'jumpsuit', 'đồ bộ',
    'bộ trang phục', 'đồ ngủ', 'đồ lót', 'áo lót'];
  return kinds.find((kind) => text.includes(kind)) || (text.includes('áo') ? 'áo' : text.includes('quần') ? 'quần' : 'trang phục');
}

function detectedMaterials(sourceText) {
  const text = sourceText.toLocaleLowerCase('vi');
  const materials = ['cotton', 'coolmax', 'linen', 'lanh', 'lụa', 'satin', 'denim', 'jean', 'kaki',
    'modal', 'nỉ', 'len', 'polyester', 'thun lạnh', 'đũi', 'viscose', 'bamboo', 'tencel', 'ren'];
  return unique(materials.filter((material) => text.includes(material)));
}

function factualAttributes(detail) {
  return unique((detail.specifications || []).flatMap((group) => group.attributes || []).map((attribute) => {
    const name = plainText(attribute.name);
    const value = plainText(attribute.value);
    return name && value && value.toLowerCase() !== 'null' ? `${name}: ${value}` : '';
  })).slice(0, 12);
}

function sourceUrl(item) {
  return `https://tiki.vn/${String(item.url_path || '').replace(/^\/+/, '')}`;
}

function buildCopy(item, detail, audience) {
  const kind = productKind(detail.name || item.name);
  const sourceFacts = `${detail.name || ''} ${plainText(detail.short_description)} ${plainText(detail.description)}`;
  const materials = detectedMaterials(sourceFacts);
  const attributes = factualAttributes(detail);
  const optionLabels = unique((detail.configurable_options || []).flatMap((option) =>
    (option.values || []).map((value) => plainText(value.label))
  )).slice(0, 18);
  const materialText = materials.length ? materials.join(', ') : 'chất liệu theo thông tin của nhà bán hàng';
  const description = [
    `${detail.name || item.name} là ${kind} dành cho ${audience}, phù hợp để bổ sung vào tủ đồ hằng ngày.`,
    `Thiết kế ưu tiên khả năng phối đồ và sự thuận tiện khi sử dụng; chất liệu được ghi nhận gồm ${materialText}.`,
    optionLabels.length
      ? `Sản phẩm có các lựa chọn màu sắc hoặc kích cỡ như ${optionLabels.slice(0, 8).join(', ')}; nên đối chiếu bảng size trước khi chọn.`
      : 'Người mua nên kiểm tra số đo thực tế và thông tin phân loại trước khi chọn.'
  ].join(' ');

  const detailHtml = [
    `<section data-source="tiki" data-source-id="${detail.id || item.id}">`,
    '<h2>Mô tả sản phẩm</h2>',
    `<p>${escapeHtml(description)}</p>`,
    '<h3>Điểm nổi bật</h3>',
    '<ul>',
    `<li>Nhóm sản phẩm: ${escapeHtml(kind)} ${escapeHtml(audience)}.</li>`,
    `<li>Chất liệu tham khảo: ${escapeHtml(materialText)}.</li>`,
    `<li>Phong cách sử dụng: dễ phối cho sinh hoạt hằng ngày, đi làm, đi học hoặc đi chơi tùy mẫu.</li>`,
    `<li>Giá bán và tồn kho được lưu theo từng phân loại để người mua chọn đúng phiên bản.</li>`,
    '</ul>',
    '<h3>Thông tin phân loại</h3>',
    `<p>${escapeHtml(optionLabels.length ? optionLabels.join(', ') : 'Sản phẩm không có phân loại được công bố.')}</p>`,
    '<h3>Thông số do nhà bán hàng công bố</h3>',
    attributes.length
      ? `<ul>${attributes.map((attribute) => `<li>${escapeHtml(attribute)}</li>`).join('')}</ul>`
      : '<p>Chưa có thêm thông số kỹ thuật được công bố.</p>',
    '<h3>Gợi ý chọn và bảo quản</h3>',
    '<ul>',
    '<li>Đối chiếu số đo cơ thể với bảng kích thước của từng phân loại; nếu ở giữa hai size, cân nhắc kiểu mặc ôm hay thoải mái.</li>',
    '<li>Giặt riêng sản phẩm sáng và tối màu trong lần đầu, dùng chất giặt dịu nhẹ và tránh ngâm lâu.</li>',
    '<li>Ưu tiên phơi nơi thoáng mát; nhiệt độ ủi và cách giặt cần điều chỉnh theo chất liệu thực tế trên nhãn sản phẩm.</li>',
    '<li>Màu sắc trên màn hình có thể chênh lệch nhẹ do ánh sáng và thiết bị hiển thị.</li>',
    '</ul>',
    `<p><small>Nguồn dữ liệu sản phẩm tham khảo: <a href="${escapeHtml(sourceUrl(item))}">Tiki #${detail.id || item.id}</a>. Nội dung mô tả đã được biên soạn lại.</small></p>`,
    '</section>'
  ].join('');
  return { description, detail: detailHtml };
}

function buildVariants(detail) {
  const variants = [];
  const seen = new Set();
  for (const source of detail.configurable_products || []) {
    if (source.inventory_status && source.inventory_status !== 'available') continue;
    const optionName = unique([source.option1, source.option2, source.option3].map(plainText)).join(' - ');
    const name = optionName || plainText(source.name).replace(plainText(detail.name), '').replace(/^\s*-\s*/, '');
    if (!name || seen.has(name)) continue;
    seen.add(name);
    const price = Number(source.price || detail.price || 0);
    const originalPrice = Math.max(price, Number(source.original_price || detail.original_price || price));
    variants.push({
      name,
      sku: `TIKI-${detail.id}-${source.sku || source.id}`.slice(0, 100),
      imageUrl: '',
      originalPrice,
      price,
      quantity: 12 + (Number(source.id || variants.length) % 19)
    });
    if (variants.length >= 20) break;
  }
  return variants;
}

function buildProduct(item, detail, audience, categoryId) {
  const copy = buildCopy(item, detail, audience);
  const variants = buildVariants(detail);
  const price = Number(detail.price || item.price || 0);
  const originalPrice = Math.max(price, Number(detail.original_price || item.original_price || price));
  const image = detail.thumbnail_url || detail.images?.[0]?.medium_url || item.thumbnail_url || '';
  return {
    name: plainText(detail.name || item.name),
    originalPrice: variants.length ? Math.min(...variants.map((variant) => variant.originalPrice)) : originalPrice,
    price: variants.length ? Math.min(...variants.map((variant) => variant.price)) : price,
    description: copy.description,
    detail: copy.detail,
    images: image ? [image] : [],
    quantity: variants.length ? variants.reduce((total, variant) => total + variant.quantity, 0) : 30,
    sold: Math.max(0, Number(item.quantity_sold?.value || 0)),
    variants,
    categoryId: String(categoryId),
    shopId: SHOP_ID,
    moderationStatus: 'approved',
    moderatedBy: 'tiki-fashion-import',
    moderatedAt: new Date(),
    moderationNote: 'Imported from public Tiki metadata; description rewritten locally.'
  };
}

async function fetchJson(url, attempts = 3) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, { headers: { accept: 'application/json', 'user-agent': USER_AGENT } });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return await response.json();
    } catch (error) {
      lastError = error;
      if (attempt < attempts) await new Promise((resolve) => setTimeout(resolve, 500 * attempt));
    }
  }
  throw lastError;
}

async function listing(source, page) {
  const url = new URL('https://tiki.vn/api/personalish/v1/blocks/listings');
  url.searchParams.set('limit', '40');
  url.searchParams.set('category', String(source.categoryId));
  url.searchParams.set('page', String(page));
  url.searchParams.set('urlKey', source.urlKey);
  return (await fetchJson(url)).data || [];
}

async function ensureCategory(source) {
  return Category.findOneAndUpdate(
    { name: source.categoryName, shopId: SHOP_ID },
    { $setOnInsert: { description: `Danh mục ${source.categoryName.toLocaleLowerCase('vi')} nhập từ dữ liệu công khai và biên soạn lại.` } },
    { new: true, upsert: true }
  );
}

async function importAudience(source) {
  const category = APPLY ? await ensureCategory(source) : { _id: 'dry-run-category' };
  const marker = new RegExp(`data-source="tiki"[^>]+data-source-id="[0-9]+"`);
  const existingCount = APPLY ? await Product.countDocuments({ shopId: SHOP_ID, categoryId: String(category._id), detail: marker }) : 0;
  const needed = Math.max(0, TARGET_PER_AUDIENCE - existingCount);
  let inserted = 0;
  const preview = [];
  const seenIds = new Set();

  for (let page = 1; page <= 8 && inserted < needed; page += 1) {
    const items = await listing(source, page);
    if (!items.length) break;
    for (const item of items) {
      if (inserted >= needed) break;
      const externalId = String(item.id || '');
      if (!externalId || seenIds.has(externalId) || item.inventory_status === 'unavailable') continue;
      seenIds.add(externalId);
      if (APPLY) {
        const markerText = `data-source-id="${externalId}"`;
        const duplicate = await Product.findOne({ $or: [
          { detail: { $regex: markerText } },
          { shopId: SHOP_ID, name: plainText(item.name) }
        ] });
        if (duplicate) continue;
      }
      const detail = await fetchJson(`https://tiki.vn/api/v2/products/${externalId}`);
      if (detail.inventory_status && detail.inventory_status !== 'available') continue;
      const payload = buildProduct(item, detail, source.audience, category._id);
      if (!payload.name || !Number.isFinite(payload.price) || payload.price <= 0) continue;
      if (APPLY) await Product.create(payload);
      preview.push({ externalId, name: payload.name, price: payload.price, variants: payload.variants.length });
      inserted += 1;
      await new Promise((resolve) => setTimeout(resolve, 80));
    }
  }
  if (inserted < needed) throw new Error(`Only prepared ${inserted}/${needed} new ${source.audience} products`);
  return { source, category, existingCount, inserted, preview };
}

async function main() {
  await connectMongo();
  if (APPLY) await initProducer();
  const results = [];
  try {
    for (const source of SOURCES) results.push(await importAudience(source));
    if (APPLY) {
      for (const result of results) {
        const imported = await Product.find({
          shopId: SHOP_ID,
          categoryId: String(result.category._id),
          detail: /data-source="tiki"/
        }).sort({ createdAt: -1 }).limit(TARGET_PER_AUDIENCE);
        for (const product of imported) await publishProductCreated(product);
      }
    }
    console.log(JSON.stringify({
      mode: APPLY ? 'applied' : 'dry-run',
      shopId: SHOP_ID,
      totals: results.map((result) => ({
        audience: result.source.audience,
        category: result.source.categoryName,
        existing: result.existingCount,
        inserted: result.inserted,
        sample: result.preview.slice(0, 3)
      }))
    }, null, 2));
  } finally {
    if (APPLY) await closeProducer();
    await mongoose.disconnect();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
