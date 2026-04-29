import { useState } from 'react';
import api from '../services/api';

export default function CreateProduct() {
  const [name, setName] = useState('');
  const [price, setPrice] = useState('');
  const [description, setDescription] = useState('');
  const [detail, setDetail] = useState('');
  const [shopId, setShopId] = useState('');
  const [images, setImages] = useState(null);

  async function submit() {
    const form = new FormData();
    form.append('name', name);
    form.append('price', price);
    form.append('description', description);
    form.append('detail', detail);
    form.append('shopId', shopId);
    if (images) {
      for (const file of images) {
        form.append('images', file);
      }
    }
    await api.post('/products', form, { headers: { 'Content-Type': 'multipart/form-data' } });
    alert('Đã tạo sản phẩm');
  }

  return (
    <div className="container page-section">
      <div className="section-header">
        <h2>Tạo sản phẩm</h2>
        <span className="section-link">Thêm sản phẩm mới</span>
      </div>
      <div className="card form-card">
        <div className="form-grid">
          <div>
            <label>Tên sản phẩm</label>
            <input placeholder="Tên sản phẩm" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label>Giá</label>
            <input placeholder="Giá" value={price} onChange={(e) => setPrice(e.target.value)} />
          </div>
          <div>
            <label>Mã shop</label>
            <input placeholder="Mã shop" value={shopId} onChange={(e) => setShopId(e.target.value)} />
          </div>
          <div>
            <label>Hình ảnh</label>
            <input type="file" multiple onChange={(e) => setImages(e.target.files)} />
          </div>
        </div>
        <label>Mô tả</label>
        <textarea placeholder="Mô tả" value={description} onChange={(e) => setDescription(e.target.value)} />
        <label>Chi tiết</label>
        <textarea placeholder="Chi tiết" value={detail} onChange={(e) => setDetail(e.target.value)} />
        <button className="btn btn-primary" onClick={submit}>Tạo sản phẩm</button>
      </div>
    </div>
  );
}
