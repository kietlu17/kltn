/* Idempotently expand sparse legacy catalog copy and publish one update per product. */
const mongoose = require('mongoose');
const { connectMongo } = require('../config/db');
const Product = require('../models/Product');
const Category = require('../models/Category');
const { htmlToPlainText } = require('../utils/catalogText');
const { initProducer, closeProducer, publishProductUpdated } = require('../kafka/producer');

const APPLY = process.argv.includes('--apply');
const ENRICHMENT_MARKER = 'catalog-v1';

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function plainText(value, limit = 3000) {
  return String(value || '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;|&#160;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, limit);
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function isClearlyBlocked(product) {
  const normalize = (value) => plainText(value, 6000)
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ');
  const blockedName = /\b(vu khi|sung|dan duoc|bom|dao gam|fake|replica|ma tuy|can sa|thuoc lac)\b/;
  const blockedDetail = /\b(vu khi|sung|dan duoc|bom|dao gam|hang gia|fake|replica|ma tuy|can sa|thuoc lac)\b/;
  const name = normalize(product.name || '');
  const shortDetail = normalize(product.detail || '').trim();
  return blockedName.test(name) || (shortDetail.length < 80 && blockedDetail.test(shortDetail));
}

function productKind(name) {
  const text = name.toLocaleLowerCase('vi');
  const kinds = ['áo sơ mi', 'áo polo', 'áo thun', 'áo khoác', 'quần tây', 'quần jeans',
    'quần jean', 'quần short', 'chân váy', 'đầm', 'váy', 'balo', 'túi xách', 'tai nghe',
    'laptop', 'máy tính', 'bàn phím', 'sách', 'giá đỡ', 'bàn chải'];
  return kinds.find((kind) => text.includes(kind)) || 'sản phẩm';
}

function detectedMaterials(textValue) {
  const text = textValue.toLocaleLowerCase('vi');
  return unique(['cotton', 'coolmax', 'linen', 'lanh', 'lụa', 'satin', 'denim', 'jean', 'kaki',
    'modal', 'nỉ', 'len', 'polyester', 'nhựa', 'kim loại', 'da', 'vải', 'giấy']
    .filter((material) => text.includes(material)));
}

function audience(name, categoryName) {
  const text = `${name} ${categoryName}`.toLocaleLowerCase('vi');
  if (text.includes('trẻ em') || text.includes('children') || text.includes('cho bé')) return 'trẻ em';
  if (text.includes(' nữ') || text.startsWith('nữ') || text.includes('women')) return 'nữ';
  if (text.includes(' nam') || text.startsWith('nam') || text.includes('men')) return 'nam';
  return 'người dùng phổ thông';
}

function buildCopy(product, categoryName) {
  const name = plainText(product.name, 500);
  const oldDescription = plainText(product.description, 1200);
  const oldDetail = plainText(product.detail, 1800);
  const kind = productKind(name);
  const target = audience(name, categoryName);
  const materials = detectedMaterials(`${name} ${oldDescription} ${oldDetail}`);
  const variantNames = unique((product.variants || []).map((variant) => plainText(variant.name, 120))).slice(0, 20);
  const materialText = materials.length ? materials.join(', ') : 'vật liệu theo thông tin trên nhãn và phân loại sản phẩm';
  const categoryText = categoryName || 'Sản phẩm tổng hợp';
  const existingFacts = oldDescription || oldDetail || `${name} thuộc danh mục ${categoryText}.`;
  const description = [
    `${name} là ${kind} thuộc danh mục ${categoryText}, hướng đến ${target}.`,
    `Sản phẩm được trình bày rõ công năng, lựa chọn và cách sử dụng để người mua dễ so sánh trước khi đặt hàng.`,
    `Thông tin chất liệu ghi nhận gồm ${materialText}; màu sắc, kích thước và cấu hình thực tế cần đối chiếu theo từng phân loại.`,
    variantNames.length
      ? `Hiện có các lựa chọn như ${variantNames.slice(0, 6).join(', ')}.`
      : 'Sản phẩm hiện không có biến thể riêng được công bố.'
  ].join(' ');

  const detail = [
    `<section data-enrichment-version="${ENRICHMENT_MARKER}">`,
    '<h2>Thông tin tổng quan</h2>',
    `<p>${escapeHtml(description)}</p>`,
    '<h3>Thông tin gốc được ghi nhận</h3>',
    `<p>${escapeHtml(existingFacts)}</p>`,
    '<h3>Đặc điểm chính</h3>',
    '<ul>',
    `<li>Loại sản phẩm: ${escapeHtml(kind)}.</li>`,
    `<li>Danh mục: ${escapeHtml(categoryText)}.</li>`,
    `<li>Đối tượng hoặc nhu cầu tham khảo: ${escapeHtml(target)}.</li>`,
    `<li>Chất liệu hoặc cấu tạo được nhận diện từ dữ liệu hiện có: ${escapeHtml(materialText)}.</li>`,
    '<li>Giá hiển thị được lấy từ phân loại có giá thấp nhất; giá cuối cùng phụ thuộc lựa chọn cụ thể.</li>',
    '<li>Tồn kho được quản lý riêng theo sản phẩm và từng biến thể để hạn chế hiển thị lựa chọn đã hết hàng.</li>',
    '</ul>',
    '<h3>Phân loại đang có</h3>',
    `<p>${escapeHtml(variantNames.length ? variantNames.join(', ') : 'Không có phân loại riêng; người mua nhận sản phẩm theo cấu hình hiển thị.')}</p>`,
    '<h3>Gợi ý lựa chọn</h3>',
    '<ul>',
    '<li>Đọc kỹ tên phân loại, kích thước, màu sắc hoặc cấu hình trước khi thêm vào giỏ.</li>',
    '<li>Với quần áo và phụ kiện, hãy đối chiếu số đo thực tế thay vì chỉ dựa vào size thường mặc.</li>',
    '<li>Với thiết bị hoặc phụ kiện điện tử, kiểm tra khả năng tương thích với thiết bị đang sử dụng.</li>',
    '<li>Nếu cần dùng cho công việc, học tập hoặc làm quà, ưu tiên phiên bản có công năng và màu sắc phù hợp hoàn cảnh.</li>',
    '</ul>',
    '<h3>Sử dụng và bảo quản</h3>',
    '<ul>',
    '<li>Làm theo hướng dẫn trên nhãn hoặc tài liệu đi kèm; tránh nhiệt độ, độ ẩm và va đập vượt quá điều kiện sử dụng thông thường.</li>',
    '<li>Với sản phẩm vải, nên giặt riêng màu sáng và tối trong lần đầu, dùng chất giặt dịu nhẹ và phơi nơi thoáng mát.</li>',
    '<li>Với sách và thiết bị, bảo quản ở nơi khô ráo, tránh ánh nắng trực tiếp và vệ sinh bằng dụng cụ phù hợp.</li>',
    '<li>Hình ảnh có thể chênh lệch nhẹ về màu do ánh sáng chụp và thiết bị hiển thị.</li>',
    '</ul>',
    '<p><small>Nội dung được chuẩn hóa từ dữ liệu catalog hiện có; không bổ sung cam kết kỹ thuật chưa được nhà bán hàng công bố.</small></p>',
    '</section>'
  ].join('');
  return { description, detail: htmlToPlainText(detail, [description, 'Thông tin tổng quan']) };
}

async function main() {
  await connectMongo();
  if (APPLY) await initProducer();
  try {
    const categories = new Map((await Category.find({}).lean()).map((category) => [String(category._id), category.name]));
    const products = await Product.find({ moderationStatus: 'approved' });
    const candidates = products.filter((product) =>
      !isClearlyBlocked(product)
      &&
      product.contentVersion !== ENRICHMENT_MARKER
      && !String(product.detail || '').includes(`data-enrichment-version="${ENRICHMENT_MARKER}"`)
      && product.sourceProvider !== 'tiki'
      && !String(product.detail || '').includes('data-source="tiki"')
      && (String(product.description || '').length < 250 || String(product.detail || '').length < 800)
    );
    const updated = [];
    for (const product of candidates) {
      const copy = buildCopy(product, categories.get(String(product.categoryId || '')) || 'Sản phẩm tổng hợp');
      if (APPLY) {
        product.description = copy.description;
        product.detail = copy.detail;
        product.contentVersion = ENRICHMENT_MARKER;
        await product.save();
      }
      updated.push({ id: String(product._id), name: product.name, descriptionLength: copy.description.length, detailLength: copy.detail.length });
    }
    if (APPLY) {
      const enriched = await Product.find({ contentVersion: ENRICHMENT_MARKER });
      for (const product of enriched) await publishProductUpdated(product);
    }
    console.log(JSON.stringify({
      mode: APPLY ? 'applied' : 'dry-run',
      candidates: candidates.length,
      updated: updated.length,
      sample: updated.slice(0, 5)
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
