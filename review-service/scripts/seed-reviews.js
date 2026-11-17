/*
 * Seed realistic Vietnamese product reviews into review-service.
 *
 * Every product gets a deterministic "character" (overall quality and, by
 * category, traits such as clothing fit, headphone sound or laptop heat) and
 * 0-14 reviews whose ratings and comments agree with it, so the shopping
 * assistant can learn "form nhỏ, nên tăng 1 size" or "bass mạnh, pin trâu"
 * from what buyers wrote. Re-running produces the same reviews (seeded by
 * product id); seeded reviews carry source="seed" and userId "seed-…".
 *
 * Run inside the review-service container (it has mongoose and MONGO_URI):
 *   docker exec -i review-service node - --dry-run < review-service/scripts/seed-reviews.js
 *   docker exec -i review-service node - < review-service/scripts/seed-reviews.js
 *   docker exec -i review-service node - --reset < review-service/scripts/seed-reviews.js
 * Options: --dry-run (print samples, write nothing), --reset (delete seeded
 * reviews first), --remove (only delete seeded reviews), --max=N (reviews per
 * product cap, default 14), --product-db=NAME (default product-service).
 */
const mongoose = require('mongoose');

const args = process.argv.slice(2);
const flag = (name) => args.includes(`--${name}`);
const option = (name, fallback) => {
  const found = args.find((item) => item.startsWith(`--${name}=`));
  return found ? found.split('=').slice(1).join('=') : fallback;
};
const DRY_RUN = flag('dry-run');
const MAX_REVIEWS = Math.max(1, Math.min(40, Number(option('max', 14)) || 14));
const PRODUCT_DB = option('product-db', 'product-service');
const MONGO_URI = process.env.MONGO_URI || 'mongodb://localhost:27017/review-service';

// -- deterministic randomness ------------------------------------------------

function hashSeed(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function rng(seedText) {
  let a = hashSeed(seedText) || 1;
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const pick = (rand, items) => items[Math.floor(rand() * items.length)];
const chance = (rand, p) => rand() < p;
function pickMany(rand, items, count) {
  const pool = [...items];
  const out = [];
  while (pool.length && out.length < count) out.push(pool.splice(Math.floor(rand() * pool.length), 1)[0]);
  return out;
}

const fold = (text) => String(text || '')
  .normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/gi, 'd').toLowerCase();

// -- reviewers -----------------------------------------------------------------

const FAMILY = ['Nguyễn', 'Trần', 'Lê', 'Phạm', 'Hoàng', 'Huỳnh', 'Phan', 'Vũ', 'Võ', 'Đặng', 'Bùi', 'Đỗ', 'Hồ', 'Ngô', 'Dương', 'Lý'];
const GIVEN = ['An', 'Anh', 'Bảo', 'Bình', 'Chi', 'Dũng', 'Duy', 'Giang', 'Hà', 'Hải', 'Hạnh', 'Hiếu', 'Hoa', 'Hùng', 'Huy',
  'Khang', 'Khánh', 'Lan', 'Linh', 'Long', 'Mai', 'Minh', 'My', 'Nam', 'Ngân', 'Ngọc', 'Nhi', 'Phong', 'Phúc', 'Quân',
  'Quỳnh', 'Sơn', 'Tâm', 'Thảo', 'Thịnh', 'Thu', 'Trang', 'Trí', 'Trung', 'Tú', 'Tuấn', 'Uyên', 'Vy', 'Yến'];
const REVIEWERS = Array.from({ length: 800 }, (_, index) => {
  const rand = rng(`reviewer-${index}`);
  const family = pick(rand, FAMILY);
  const given = pick(rand, GIVEN);
  const style = rand();
  const userName = style < 0.45 ? `${family} ${given}` : style < 0.8 ? `${given} ${family.charAt(0)}.` : `${given}${Math.floor(rand() * 99)}`;
  return { userId: `seed-user-${String(index + 1).padStart(4, '0')}`, userName };
});

// -- category groups -----------------------------------------------------------

// Vietnamese product names start with the product kind ("Quần suông … có
// túi" is trousers, "Túi laptop" a bag), so the head of the name decides
// first and the category path second. Matching keeps diacritics: folded,
// "đẹp" and "dép" are the same word.
const NAME_HEADS = [
  ['clothes', /^(?:(?:hộp|combo|set|bộ)\s+(?:\d+\s+)?(?:quần|áo|đồ)|áo|quần|váy|đầm|chân váy|bộ đồ|đồ bộ|bộ quần áo|hoodie|sơ mi|jacket|jean|legging|yếm|pijama|đồ ngủ)(?![\p{L}])/u],
  ['shoes', /^(?:giày|dép|sandal|sneaker|guốc|boot)(?![\p{L}])/u],
  ['bag', /^(?:túi|balo|ba lô|vali|cặp|ví|bóp)(?![\p{L}])/u],
  ['audio', /^(?:tai nghe|loa|headphone|earbuds?)(?![\p{L}])/u],
  ['phone', /^(?:điện thoại|smartphone|iphone|samsung galaxy)(?![\p{L}])/u],
  ['peripheral', /^(?:bàn phím|chuột|lót chuột|giá đỡ|chân đế|đế tản|đế|hub|ổ cứng|usb|cáp|sạc|củ sạc|router|webcam)(?![\p{L}])/u],
  ['computer', /^(?:laptop|pc|máy tính|màn hình)(?![\p{L}])/u],
  ['appliance', /^(?:nồi|máy xay|máy sấy|quạt|ấm|bàn là|bàn ủi|máy lọc|máy hút|lò|bếp điện|máy ép)(?![\p{L}])/u],
  ['beauty', /^(?:son|kem|serum|sữa rửa mặt|tẩy trang|nước hoa|dầu gội|dầu xả|mặt nạ|phấn|mascara|cọ|bông tẩy|bàn chải|lược|toner|xịt)(?![\p{L}])/u],
  ['stationery', /^(?:bút|vở|sổ|giấy|thước|hộp bút|bìa|kẹp|băng keo|máy tính cầm tay|bảng)(?![\p{L}])/u],
  ['book', /^(?:sách|truyện|tiểu thuyết)(?![\p{L}])/u],
  ['accessory', /^(?:mũ|nón|kính|thắt lưng|đồng hồ|vòng|nhẫn|khăn|tất|vớ|găng)(?![\p{L}])/u],
  ['food', /^(?:bánh|kẹo|trà|cà phê|hạt|nước|sữa|mì|snack)(?![\p{L}])/u],
  ['home', /^(?:bộ nồi|chảo|dao|thớt|bát|đĩa|cốc|ly|chai|bình|chăn|ga|gối|nệm|rèm|thảm|kệ|tủ|bàn|ghế|đèn|hộp|khay|móc|giỏ)(?![\p{L}])/u],
];
const PATH_GROUPS = [
  ['shoes', /giày|dép/u], ['bag', /túi|balo|vali|du lịch/u], ['accessory', /phụ kiện/u],
  ['audio', /tai nghe|loa/u], ['phone', /điện thoại/u],
  ['peripheral', /ban phim|bàn phím|giá đỡ|thiết bị số|linh kiện/u],
  ['computer', /laptop|pc|máy vi tính/u],
  ['appliance', /điện gia dụng/u], ['beauty', /làm đẹp|sức khỏe/u], ['stationery', /văn phòng phẩm/u],
  ['book', /sách|books?|fiction|literature|thriller|literary|teaching|picture/u], ['food', /thực phẩm|đồ ăn|đồ uống/u],
  ['clothes', /thời trang/u], ['home', /nhà cửa|nội thất|dệt may|đồ dùng gia đình/u],
];

function groupOf(path, name) {
  // "MUJI Đồng hồ…", "[KoSuyTu] Giá đỡ…": the kind comes after the label.
  const head = String(name || '').normalize('NFC').toLowerCase().trim()
    .replace(/^(?:\[[^\]]*\]\s*|muji\s+|combo\s+)+/u, '');
  for (const [group, pattern] of NAME_HEADS) if (pattern.test(head)) return group;
  const branch = path.slice(1).join(' › ').normalize('NFC').toLowerCase() || path.join(' ').toLowerCase();
  for (const [group, pattern] of PATH_GROUPS) if (pattern.test(branch)) return group;
  const root = (path[0] || '').normalize('NFC').toLowerCase();
  for (const [group, pattern] of PATH_GROUPS) if (pattern.test(root)) return group;
  return 'generic';
}

// Product traits per group: one value is drawn per product and every review
// of that product describes the same trait, so the signal is consistent.
const TRAITS = {
  clothes: {
    fit: ['nhỏ', 'chuẩn', 'chuẩn', 'rộng'],
    fabric: ['mềm mát', 'dày dặn', 'mỏng nhẹ', 'hơi nóng'],
    color: ['đúng ảnh', 'đúng ảnh', 'hơi đậm hơn ảnh', 'nhạt hơn ảnh'],
  },
  shoes: { fit: ['nhỏ', 'chuẩn', 'chuẩn', 'rộng'], comfort: ['êm', 'êm', 'hơi cứng'] },
  audio: {
    sound: ['bass mạnh', 'cân bằng', 'cân bằng', 'treble sáng'],
    battery: ['trâu', 'ổn', 'hơi yếu'],
    mic: ['rõ', 'tạm được'],
    comfort: ['êm tai', 'hơi cấn tai sau 2 tiếng'],
  },
  phone: { battery: ['trâu', 'ổn', 'hơi yếu'], camera: ['đẹp', 'ổn', 'chụp tối hơi nhiễu'], heat: ['mát', 'hơi ấm khi chơi game'] },
  computer: { performance: ['mượt', 'mượt', 'đủ dùng văn phòng'], heat: ['mát', 'hơi nóng khi tải nặng'], build: ['chắc chắn', 'hơi ọp ẹp'] },
  peripheral: { build: ['chắc chắn', 'chắc chắn', 'hơi ọp ẹp'], feel: ['êm', 'ổn'], connect: ['ổn định', 'thỉnh thoảng chập chờn'] },
  appliance: { power: ['mạnh', 'vừa đủ'], noise: ['êm', 'hơi ồn'] },
  beauty: { skin: ['dịu nhẹ', 'dịu nhẹ', 'hơi châm chích với da nhạy cảm'], scent: ['thơm nhẹ', 'không mùi', 'mùi hơi nồng'], texture: ['thấm nhanh', 'hơi bết'] },
  stationery: { quality: ['mực đều', 'giấy dày', 'chất lượng vừa phải'] },
  bag: { capacity: ['rộng rãi', 'vừa đủ', 'hơi nhỏ'], material: ['bền chắc', 'chống nước tốt', 'vải hơi mỏng'] },
  accessory: { finish: ['sắc nét', 'tinh tế', 'hơi thô'] },
  home: { material: ['chắc chắn', 'mềm mịn', 'hơi mỏng'], assembly: ['dễ lắp', 'lắp hơi lâu'] },
  food: { taste: ['ngon', 'vừa miệng', 'hơi ngọt'], date: ['date xa', 'date còn dài'] },
  book: { paper: ['giấy đẹp', 'in rõ nét', 'giấy hơi mỏng'], content: ['cuốn', 'bổ ích', 'hơi dài dòng'] },
  generic: { quality: ['ổn', 'tốt', 'tạm được'] },
};

// Sentences per trait value: [positive-leaning, critical-leaning] variants.
function traitSentences(group, traits, rand, rating, name = '') {
  const lowerName = String(name).normalize('NFC').toLowerCase();
  const t = traits;
  const out = [];
  const good = rating >= 4;
  switch (group) {
    case 'clothes': {
      const garment = /^(?:quần|chân váy|váy|đầm)(?![\p{L}])/u.test(lowerName.replace(/^muji\s+/u, ''))
        ? (lowerName.replace(/^muji\s+/u, '').match(/^(?:quần|chân váy|váy|đầm)/u)[0].replace(/^./u, (c) => c.toUpperCase()))
        : 'Áo';
      out.push(
        t.fit === 'nhỏ' ? pick(rand, ['Form hơi nhỏ, mọi người nên lấy tăng 1 size.', `${garment} ôm hơn mình nghĩ, nên lên 1 size so với bình thường.`, 'Size hơi nhỏ so với bảng size, mình đổi lên 1 size mới vừa.'])
          : t.fit === 'rộng' ? pick(rand, ['Form rộng, ai thích mặc vừa thì nên lùi 1 size.', 'Size hơi rộng so với bảng size, mặc kiểu oversize thì ổn.', 'Form to, mình thường mặc L mà lấy M là vừa.'])
            : pick(rand, ['Size chuẩn theo bảng size của shop.', 'Mặc vừa form, đúng như bảng size.', 'Form chuẩn, mình lấy đúng size thường mặc.']),
      );
      out.push(
        t.fabric === 'mềm mát' ? pick(rand, ['Vải mềm, mặc mát, thấm hút mồ hôi tốt.', 'Chất vải mềm mịn, mặc cả ngày không bí.'])
          : t.fabric === 'dày dặn' ? pick(rand, ['Vải dày dặn, đứng form, giặt không bị xù.', 'Chất vải dày, cầm chắc tay.'])
            : t.fabric === 'mỏng nhẹ' ? pick(rand, ['Vải mỏng nhẹ, mặc hè rất mát nhưng màu sáng hơi xuyên.', 'Chất vải mỏng, nhẹ, hợp mặc mùa hè.'])
              : pick(rand, ['Vải hơi bí nóng nếu mặc trời nắng.', 'Chất vải hơi nóng, hợp mặc phòng máy lạnh hơn.']),
      );
      if (chance(rand, 0.6)) {
        out.push(t.color === 'đúng ảnh' ? 'Màu đúng như ảnh.' : `Màu ngoài ${t.color}${good ? ' nhưng vẫn đẹp' : ''}.`);
      }
      if (chance(rand, 0.4)) out.push(good ? 'Đường may chắc, không có chỉ thừa.' : 'Đường may có vài chỗ chỉ thừa.');
      if (chance(rand, 0.3)) out.push(good ? 'Giặt máy vài lần vẫn giữ màu, không co.' : 'Giặt lần đầu hơi co một chút.');
      break;
    }
    case 'shoes':
      out.push(t.fit === 'nhỏ' ? 'Giày form nhỏ, nên lấy tăng nửa đến 1 size.' : t.fit === 'rộng' ? 'Form giày hơi rộng, chân bè thì vừa, chân thon nên lùi 1 size.' : 'Size giày chuẩn, đi vừa chân.');
      out.push(t.comfort === 'êm' ? 'Đế êm, đi bộ cả ngày không mỏi.' : 'Đế hơi cứng, mấy ngày đầu hơi đau gót.');
      break;
    case 'audio':
      out.push(t.sound === 'bass mạnh' ? pick(rand, ['Âm bass mạnh, nghe EDM, rap rất đã.', 'Bass sâu và mạnh, hợp ai thích nhạc sôi động.'])
        : t.sound === 'cân bằng' ? pick(rand, ['Âm thanh cân bằng, mid rõ, nghe acoustic và ballad hay.', 'Chất âm cân bằng, nghe lâu không mệt tai.'])
          : pick(rand, ['Treble sáng, nghe vocal rõ nhưng bass hơi mỏng.', 'Âm hơi thiên cao, ai thích bass chắc sẽ thấy thiếu.']));
      const wired = /có dây|lightning|3\.5|type-c|jack/u.test(lowerName);
      if (!wired) out.push(t.battery === 'trâu' ? 'Pin trâu, dùng cả tuần mới phải sạc.' : t.battery === 'ổn' ? 'Pin dùng được khoảng một ngày, ổn so với giá.' : 'Pin hơi yếu, nghe liên tục tầm 3-4 tiếng là hết.');
      if (chance(rand, 0.5)) out.push(t.mic === 'rõ' ? 'Mic đàm thoại rõ, gọi điện bên kia nghe tốt.' : 'Mic gọi điện ở chỗ ồn thì bên kia nghe hơi rè.');
      if (chance(rand, 0.4)) out.push(t.comfort === 'êm tai' ? 'Đeo êm, lâu không đau tai.' : 'Đeo lâu hơi cấn tai.');
      if (!wired) out.push(good ? 'Kết nối Bluetooth nhanh, ổn định.' : 'Thỉnh thoảng bị ngắt kết nối khi để điện thoại xa.');
      break;
    case 'phone':
      out.push(t.battery === 'trâu' ? 'Pin trâu, dùng mạng xã hội cả ngày vẫn còn.' : t.battery === 'ổn' ? 'Pin đủ dùng một ngày.' : 'Pin tụt hơi nhanh khi xem video.');
      out.push(t.camera === 'đẹp' ? 'Camera chụp đẹp, màu tươi, chụp tối vẫn ổn.' : t.camera === 'ổn' ? 'Camera chụp ban ngày ổn, đủ dùng.' : 'Camera chụp đêm hơi nhiễu.');
      if (chance(rand, 0.6)) out.push(t.heat === 'mát' ? 'Máy mát, chơi game nhẹ không nóng.' : 'Chơi game lâu máy hơi ấm.');
      if (chance(rand, 0.4)) out.push(good ? 'Màn hình sáng, vuốt mượt.' : 'Màn hình ngoài nắng hơi khó nhìn.');
      break;
    case 'computer':
      out.push(t.performance === 'mượt' ? 'Máy chạy mượt, mở nhiều tab và phần mềm không giật.' : 'Hiệu năng đủ dùng văn phòng, học tập; làm đồ họa nặng thì hơi đuối.');
      out.push(t.heat === 'mát' ? 'Máy mát, quạt êm.' : 'Khi chạy tác vụ nặng máy hơi nóng, quạt kêu to.');
      if (chance(rand, 0.5)) out.push(t.build === 'chắc chắn' ? 'Hoàn thiện chắc chắn, cầm đầm tay.' : 'Vỏ nhựa hơi ọp ẹp so với giá.');
      break;
    case 'peripheral':
      out.push(t.build === 'chắc chắn' ? 'Hoàn thiện chắc chắn, cầm đầm tay.' : 'Vỏ nhựa hơi ọp ẹp so với giá.');
      if (/bàn phím/u.test(lowerName)) out.push(t.feel === 'êm' ? 'Phím gõ êm, nảy tốt.' : 'Phím gõ ổn, hơi ồn khi gõ nhanh.');
      out.push(t.connect === 'ổn định' ? 'Kết nối ổn định, cắm vào là dùng.' : 'Thỉnh thoảng kết nối hơi chập chờn.');
      break;
    case 'appliance':
      out.push(t.power === 'mạnh' ? 'Máy chạy mạnh, dùng nhanh.' : 'Công suất vừa đủ cho gia đình nhỏ.');
      out.push(t.noise === 'êm' ? 'Chạy khá êm.' : 'Lúc chạy hơi ồn.');
      if (chance(rand, 0.4)) out.push(good ? 'Dễ vệ sinh.' : 'Vệ sinh hơi mất công.');
      break;
    case 'beauty':
      out.push(t.skin === 'dịu nhẹ' ? 'Dùng dịu nhẹ, da mình nhạy cảm cũng không bị kích ứng.' : 'Da nhạy cảm dùng hơi châm chích, nên thử ở vùng nhỏ trước.');
      out.push(t.texture === 'thấm nhanh' ? 'Thấm nhanh, không bết dính.' : 'Hơi bết, hợp dùng buổi tối hơn.');
      if (chance(rand, 0.5)) out.push(t.scent === 'mùi hơi nồng' ? 'Mùi hơi nồng.' : t.scent === 'không mùi' ? 'Gần như không mùi.' : 'Mùi thơm nhẹ dễ chịu.');
      if (chance(rand, 0.3)) out.push(good ? 'Hàng có tem, date xa.' : 'Vỏ hộp hơi móp khi nhận.');
      break;
    case 'stationery':
      out.push(t.quality === 'mực đều' ? 'Viết trơn, mực ra đều.' : t.quality === 'giấy dày' ? 'Giấy dày, viết bút gel không bị lem.' : 'Chất lượng vừa phải so với giá.');
      if (chance(rand, 0.5)) out.push(good ? 'Mẫu mã dễ thương, dùng đi học rất hợp.' : 'Mẫu ngoài không đẹp bằng ảnh.');
      break;
    case 'bag':
      out.push(t.capacity === 'rộng rãi' ? 'Ngăn rộng, đựng được laptop 15 inch và nhiều đồ.' : t.capacity === 'vừa đủ' ? 'Sức chứa vừa đủ cho đồ đi làm hằng ngày.' : 'Hơi nhỏ, chỉ đựng được đồ cơ bản.');
      out.push(t.material === 'bền chắc' ? 'Chất liệu bền, khóa kéo trơn.' : t.material === 'chống nước tốt' ? 'Đi mưa nhẹ đồ bên trong không bị ướt.' : 'Vải hơi mỏng, không biết dùng lâu có bền không.');
      break;
    case 'accessory':
      out.push(t.finish === 'hơi thô' ? 'Hoàn thiện hơi thô so với ảnh.' : `Hoàn thiện ${t.finish}, nhìn sang hơn giá tiền.`);
      break;
    case 'home':
      out.push(t.material === 'chắc chắn' ? 'Chất liệu chắc chắn, dùng ổn định.' : t.material === 'mềm mịn' ? 'Chất vải mềm mịn, nằm dễ chịu.' : 'Chất liệu hơi mỏng so với mong đợi.');
      if (/^(?:kệ|tủ|bàn|ghế|giường|giá|móc)(?![\p{L}])/u.test(lowerName)) {
        out.push(t.assembly === 'dễ lắp' ? 'Lắp đặt dễ, có hướng dẫn rõ.' : 'Lắp hơi lâu, hướng dẫn chưa rõ lắm.');
      }
      break;
    case 'food':
      out.push(t.taste === 'ngon' ? 'Ăn ngon, cả nhà đều thích.' : t.taste === 'vừa miệng' ? 'Vị vừa miệng.' : 'Vị hơi ngọt so với khẩu vị của mình.');
      out.push(`Hàng ${t.date}, đóng gói kỹ.`);
      break;
    case 'book':
      out.push(t.paper === 'giấy hơi mỏng' ? 'Giấy hơi mỏng.' : `Sách ${t.paper}.`);
      out.push(t.content === 'cuốn' ? 'Nội dung cuốn, đọc một mạch.' : t.content === 'bổ ích' ? 'Nội dung bổ ích, đáng đọc.' : 'Nội dung hơi dài dòng ở vài chương.');
      break;
    default:
      out.push(t.quality === 'tạm được' ? 'Chất lượng tạm được.' : `Chất lượng ${t.quality} so với giá.`);
  }
  return out;
}

const OPENERS = {
  5: ['Rất hài lòng!', 'Sản phẩm tuyệt vời.', 'Quá ưng luôn.', 'Mua lần 2 rồi, vẫn chất lượng.', 'Đáng tiền.', ''],
  4: ['Khá ổn.', 'Hài lòng.', 'Sản phẩm tốt.', 'Ổn trong tầm giá.', ''],
  3: ['Tạm được.', 'Bình thường.', 'Cũng được, không quá xuất sắc.', ''],
  2: ['Hơi thất vọng.', 'Chưa như kỳ vọng.', 'Không đáng giá lắm.'],
  1: ['Rất thất vọng.', 'Không hài lòng.', 'Không nên mua.'],
};
const CLOSERS = {
  5: ['Sẽ ủng hộ shop tiếp.', 'Recommend cho mọi người.', 'Giao hàng nhanh, đóng gói cẩn thận.', ''],
  4: ['Giao hàng nhanh.', 'Shop tư vấn nhiệt tình.', 'Nhìn chung đáng mua.', ''],
  3: ['Giá như vậy thì chấp nhận được.', 'Giao hơi chậm.', ''],
  2: ['Mong shop cải thiện.', 'Giao hàng chậm.', ''],
  1: ['Đã liên hệ shop để đổi trả.', 'Sẽ không mua lại.', ''],
};

function drawRating(rand, quality) {
  // Mostly around the product's quality, with the occasional outlier.
  const noise = (rand() + rand() + rand() - 1.5) * 1.3;
  let value = Math.round(quality + noise);
  if (chance(rand, 0.04)) value = 1 + Math.floor(rand() * 2);
  return Math.max(1, Math.min(5, value));
}

// Tone of a trait sentence: size/fit facts are information every buyer
// mentions; the rest praise or criticise.
const CRITICAL = /(?<![\p{L}])hơi |yếu|nhiễu|ọp ẹp|hơi thô|hơi bết|nồng|chậm|không đẹp|vài chỗ chỉ thừa|co một|châm chích|đuối|cấn|ngắt|rè|thiếu|xuyên|khó nhìn|hơi ấm|hơi ồn|quạt kêu|mất công|móp|dài dòng|chỉ đựng|không biết|chập chờn|đau gót|mỏng\./u;
const INFO = /size|form/u;
const GENERIC_PRAISE = ['Chất lượng tốt so với giá.', 'Đúng như mô tả.', 'Dùng ổn, không có gì để chê.'];
const GENERIC_CRITIC = ['Chất lượng không như mô tả.', 'Dùng một thời gian là xuống cấp.', 'Không đáng với giá tiền.'];
const lowerFirst = (text) => text.charAt(0).toLowerCase() + text.slice(1);

function buildComment(rand, group, traits, rating, variantName, name) {
  const sentences = traitSentences(group, traits, rand, rating, name);
  const info = sentences.filter((text) => INFO.test(text));
  const rest = sentences.filter((text) => !INFO.test(text));
  const negative = rest.filter((text) => CRITICAL.test(text));
  const positive = rest.filter((text) => !CRITICAL.test(text));
  const body = [...pickMany(rand, info, 1)];
  if (rating >= 4) {
    body.push(...pickMany(rand, positive.length ? positive : GENERIC_PRAISE, 1 + Math.floor(rand() * 2)));
    if (negative.length && chance(rand, rating === 5 ? 0.25 : 0.5)) body.push(`Điểm trừ nhỏ là ${lowerFirst(pick(rand, negative))}`);
  } else if (rating === 3) {
    body.push(...pickMany(rand, positive.length ? positive : GENERIC_PRAISE, 1));
    body.push(`Nhưng ${lowerFirst(pick(rand, negative.length ? negative : GENERIC_CRITIC))}`);
  } else {
    body.push(...pickMany(rand, negative.length ? negative : GENERIC_CRITIC, 1 + Math.floor(rand() * 2)));
    if (positive.length && chance(rand, 0.3)) body.push(`Được cái ${lowerFirst(pick(rand, positive))}`);
  }
  const parts = [];
  const opener = pick(rand, OPENERS[rating]);
  if (opener) parts.push(opener);
  if (variantName && !/\d{4,}/.test(variantName) && chance(rand, 0.55)) parts.push(`Mình mua bản ${variantName}.`);
  parts.push(...body);
  const closer = pick(rand, CLOSERS[rating]);
  if (closer) parts.push(closer);
  // Some buyers only leave stars or a one-liner.
  if (chance(rand, 0.08)) return '';
  if (chance(rand, 0.1)) return (opener || body[0] || '').trim();
  return parts.join(' ');
}

function productPlan(product, path) {
  const id = String(product._id);
  const rand = rng(`product-${id}`);
  const group = groupOf(path, product.name || '');
  const traits = Object.fromEntries(
    Object.entries(TRAITS[group] || TRAITS.generic).map(([key, values]) => [key, pick(rand, values)])
  );
  // Overall quality 2.6-4.9, skewed high like real marketplaces; critical
  // traits pull it down a little so stars and comments agree.
  let quality = 3.4 + rand() * 1.5;
  if (chance(rand, 0.12)) quality = 2.6 + rand() * 0.9;
  const critical = Object.values(traits).filter((value) => /hoi|yeu|nhieu|cham|nong|o ep|mong|tho|bet|ong|ngot|dai dong/.test(fold(value))).length;
  quality = Math.max(2.4, quality - critical * 0.15);
  const sold = Number(product.sold || 0);
  const base = sold > 0 ? Math.min(MAX_REVIEWS, 2 + Math.round(Math.log2(1 + sold))) : Math.floor(rand() * (MAX_REVIEWS + 1));
  const count = chance(rand, 0.1) ? 0 : Math.max(0, Math.min(MAX_REVIEWS, base + Math.floor(rand() * 3) - 1));
  return { id, rand, group, traits, quality, count };
}

async function main() {
  await mongoose.connect(MONGO_URI);
  const reviews = mongoose.connection.collection('reviews');
  const productDb = mongoose.connection.useDb(PRODUCT_DB, { useCache: true });

  if (flag('reset') || flag('remove')) {
    const removed = DRY_RUN ? { deletedCount: 'dry-run' } : await reviews.deleteMany({ source: 'seed' });
    console.log(`Removed seeded reviews: ${removed.deletedCount}`);
    if (flag('remove')) { await mongoose.disconnect(); return; }
  }

  const categories = await productDb.collection('categories').find({}, { projection: { name: 1, parentId: 1 } }).toArray();
  const byId = new Map(categories.map((item) => [String(item._id), item]));
  const pathOf = (categoryId) => {
    const path = [];
    let node = categoryId ? byId.get(String(categoryId)) : null;
    for (let guard = 0; node && guard < 10; guard += 1) {
      path.unshift(node.name);
      node = node.parentId ? byId.get(String(node.parentId)) : null;
    }
    return path;
  };

  const products = await productDb.collection('products')
    .find({ moderationStatus: 'approved' }, { projection: { name: 1, categoryId: 1, variants: 1, sold: 1, createdAt: 1 } })
    .toArray();
  const now = Date.now();
  const operations = [];
  const groups = {};
  const samples = [];
  for (const product of products) {
    const plan = productPlan(product, pathOf(product.categoryId));
    groups[plan.group] = (groups[plan.group] || 0) + 1;
    const reviewers = pickMany(plan.rand, REVIEWERS, plan.count);
    const variants = (product.variants || [])
      .map((item) => String((item && item.name) || '').trim())
      .filter(Boolean)
      // "ĐEN / 14 INCH" reads better as a buyer would type it.
      .map((name) => (name === name.toUpperCase() ? name.toLowerCase() : name));
    const since = Math.max(new Date(product.createdAt || now - 365 * 864e5).getTime(), now - 365 * 864e5);
    for (const reviewer of reviewers) {
      const rating = drawRating(plan.rand, plan.quality);
      const variantName = variants.length > 1 ? pick(plan.rand, variants) : '';
      const comment = buildComment(plan.rand, plan.group, plan.traits, rating, variantName, product.name);
      const createdAt = new Date(since + plan.rand() * Math.max(1, now - since));
      const doc = {
        productId: plan.id,
        userId: reviewer.userId,
        userName: reviewer.userName,
        rating,
        comment,
        source: 'seed',
        createdAt,
        updatedAt: createdAt,
      };
      if (comment && samples.filter((item) => item.group === plan.group).length < 2 && plan.rand() < 0.1) {
        samples.push({ name: product.name, group: plan.group, ...doc });
      }
      operations.push({
        updateOne: {
          filter: { productId: doc.productId, userId: doc.userId },
          // A real buyer's review for the same product/user is never overwritten.
          update: { $setOnInsert: doc },
          upsert: true,
        },
      });
    }
  }

  console.log(`Products: ${products.length}, reviews to seed: ${operations.length}`);
  console.log('Products per group:', groups);
  for (const sample of samples) {
    console.log(`- [${sample.group}] ${sample.name} | ${sample.rating}★ ${sample.userName}: ${sample.comment}`);
  }
  if (DRY_RUN) {
    console.log('Dry run: nothing written.');
    await mongoose.disconnect();
    return;
  }
  let inserted = 0;
  for (let index = 0; index < operations.length; index += 1000) {
    const result = await reviews.bulkWrite(operations.slice(index, index + 1000), { ordered: false });
    inserted += result.upsertedCount || 0;
  }
  console.log(`Inserted ${inserted} new reviews (${operations.length - inserted} already existed).`);
  await mongoose.disconnect();
}

main().catch(async (error) => {
  console.error(error);
  await mongoose.disconnect().catch(() => {});
  process.exit(1);
});
