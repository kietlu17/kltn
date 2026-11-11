// node --test tests
const test = require('node:test');
const assert = require('node:assert/strict');
const { canonicalPath } = require('../src/utils/categoryTaxonomy');
const { planTree } = require('../src/scripts/buildCategoryTree');

test('source names map onto one shared tree', () => {
  assert.deepEqual(canonicalPath('YODY · Áo thun nữ'), ['Thời trang', 'Nữ', 'Áo thun nữ']);
  assert.deepEqual(canonicalPath('YODY · Đầm và chân váy bé gái'), ['Thời trang', 'Trẻ em', 'Đầm và chân váy bé gái']);
  assert.deepEqual(canonicalPath('YODY · Áo Giữ Nhiệt Nam XTRA-HEAT'), ['Thời trang', 'Nam', 'Áo Giữ Nhiệt Nam XTRA-HEAT']);
  assert.deepEqual(canonicalPath('YODY · Nam'), ['Thời trang', 'Nam']);
  assert.deepEqual(canonicalPath('Thời trang nữ'), ['Thời trang', 'Nữ']);
  assert.deepEqual(canonicalPath('Laptop'), ['Điện tử', 'Laptop']);
  assert.deepEqual(canonicalPath('MUJI · Quần áo › Trang Phục Nữ › Áo Thun › 053:L&S T-SHIRT'),
    ['Thời trang', 'Nữ', 'Áo Thun', 'L&S T-SHIRT']);
  assert.deepEqual(canonicalPath('MUJI · Nhà Cửa Đời Sống › Đồ Điện Tử › Quạt'), ['Điện tử', 'Đồ điện gia dụng', 'Quạt']);
  assert.deepEqual(canonicalPath('MUJI · Quần áo'), ['Thời trang', 'Tổng hợp']);
  assert.deepEqual(canonicalPath('YODY · Sản phẩm khác'), ['Khác', 'Sản phẩm khác']);
});

test('the plan links seller categories under shared platform nodes', () => {
  const categories = [
    { _id: 'a1', shopId: 'A', name: 'YODY · Nam' },
    { _id: 'a2', shopId: 'A', name: 'YODY · Áo thun nam' },
    { _id: 'a3', shopId: 'A', name: 'MUJI · Quần áo › Trang Phục Nam › Áo Thun' },
    { _id: 'a4', shopId: 'A', name: 'MUJI · Quần áo › Trang Phục Nam › Áo Thun › 009:L&S T-SHIRT' },
    { _id: 'b1', shopId: 'B', name: 'Laptop' },
    { _id: 'b2', shopId: 'B', name: 'Áo thun nam' }
  ];
  const { create, update } = planTree(categories);
  const byId = Object.fromEntries(update.map((item) => [item.id, item]));
  assert.deepEqual(create.map((item) => item.path).sort(), ['Thời trang', 'Thời trang › Nam', 'Điện tử'].sort());
  // Roots are platform nodes; below them the shop's own node is reused.
  assert.equal(byId.a1.parentId, 'new:Thời trang');
  assert.equal(byId.a2.parentId, 'a1');
  assert.equal(byId.a3.parentId, 'a1');
  assert.equal(byId.a4.parentId, 'a3');
  assert.equal(byId.a4.name, 'L&S T-SHIRT');
  assert.equal(byId.a2.name, 'Áo thun nam');
  assert.equal(byId.a2.sourceName, 'YODY · Áo thun nam');
  // Another shop has no "Nam" of its own and uses the platform node.
  assert.equal(byId.b2.parentId, 'new:Thời trang › Nam');
  assert.equal(byId.b1.path, 'Điện tử › Laptop');
});

test('the plan is idempotent on migrated data', () => {
  const first = planTree([{ _id: 'a2', shopId: 'A', name: 'YODY · Áo thun nữ' }]);
  const migrated = [
    { _id: 'p1', shopId: 'platform', name: 'Thời trang', parentId: null, path: 'Thời trang' },
    { _id: 'p2', shopId: 'platform', name: 'Nữ', parentId: 'p1', path: 'Thời trang › Nữ' },
    { _id: 'a2', shopId: 'A', name: 'Áo thun nữ', sourceName: 'YODY · Áo thun nữ', parentId: 'p2' }
  ];
  const second = planTree(migrated);
  assert.equal(first.create.length, 2);
  assert.equal(second.create.length, 0);
  assert.equal(second.update[0].parentId, 'p2');
  assert.equal(second.update[0].name, 'Áo thun nữ');
});

function memoryCategoryModel() {
  const rows = [];
  let next = 1;
  const matches = (row, filter) => Object.entries(filter).every(([field, value]) => (row[field] ?? null) === value);
  return {
    rows,
    async findOne(filter) {
      return rows.find((row) => matches(row, filter)) || null;
    },
    async findOneAndUpdate(filter, update) {
      let row = rows.find((item) => matches(item, filter));
      if (!row) {
        row = { _id: `id${next++}`, ...filter, ...(update.$setOnInsert || {}) };
        rows.push(row);
      }
      Object.assign(row, update.$set || {});
      return row;
    }
  };
}

test('importers place new categories in the shared tree', async () => {
  const { ensureCategoryPath } = require('../src/utils/categoryTaxonomy');
  const Category = memoryCategoryModel();
  const yody = await ensureCategoryPath(Category, canonicalPath('Áo thun nữ'), 'shopA');
  const again = await ensureCategoryPath(Category, canonicalPath('Áo thun nữ'), 'shopA');
  const laptop = await ensureCategoryPath(Category, canonicalPath('Laptop'), 'shopB');
  assert.equal(again._id, yody._id);
  assert.equal(yody.shopId, 'shopA');
  assert.equal(yody.path, 'Thời trang › Nữ › Áo thun nữ');
  const parent = Category.rows.find((row) => row._id === yody.parentId);
  assert.deepEqual([parent.name, parent.shopId], ['Nữ', 'platform']);
  assert.equal(laptop.path, 'Điện tử › Laptop');
  // Roots are shared platform nodes, created once.
  assert.equal(Category.rows.filter((row) => row.level === 0).length, 2);
});

test('seller-typed names in the live catalog are classified', () => {
  assert.deepEqual(canonicalPath('pc'), ['Điện tử', 'PC']);
  assert.deepEqual(canonicalPath('ban phim'), ['Điện tử', 'Ban phim']);
  assert.deepEqual(canonicalPath('Laptop Truyền Thống'), ['Điện tử', 'Laptop Truyền Thống']);
  assert.deepEqual(canonicalPath('Tai Nghe Có Dây Nhét Tai'), ['Điện tử', 'Tai Nghe Có Dây Nhét Tai']);
  assert.deepEqual(canonicalPath("Children's Books"), ['Sách', "Children's Books"]);
  assert.deepEqual(canonicalPath('Nhà Cửa - Đời Sống'), ['Nhà cửa & Đời sống', 'Tổng hợp']);
  assert.deepEqual(canonicalPath('Phụ kiện thời trang nam khác'), ['Thời trang', 'Nam', 'Phụ kiện thời trang nam khác']);
});
