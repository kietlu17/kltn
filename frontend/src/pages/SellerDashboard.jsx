import { Link } from 'react-router-dom';
import { useState } from 'react';
import api from '../services/api';

export default function SellerDashboard() {
  const [name, setName] = useState('');
  const [ownerId, setOwnerId] = useState('seller-1');
  const [description, setDescription] = useState('');

  async function createShop() {
    await api.post('/shops', { name, ownerId, description });
    alert('Đã tạo shop');
  }

  return (
    <div className="container page-section seller-dashboard">
      <div className="section-header">
        <h2>Bảng điều khiển người bán</h2>
        <span className="section-link">Quản lý gian hàng của bạn</span>
      </div>
      <div className="seller-grid">
        <div className="card">
          <h3>Tạo shop</h3>
          <label>Tên shop</label>
          <input placeholder="Tên shop" value={name} onChange={(e) => setName(e.target.value)} />
          <label>Mã chủ shop</label>
          <input placeholder="Mã chủ shop" value={ownerId} onChange={(e) => setOwnerId(e.target.value)} />
          <label>Mô tả</label>
          <textarea placeholder="Mô tả" value={description} onChange={(e) => setDescription(e.target.value)} />
          <button className="btn btn-primary" onClick={createShop}>Tạo shop</button>
        </div>
        <div className="card">
          <h3>Quản lý sản phẩm</h3>
          <p className="muted">Tạo, sửa hoặc xóa sản phẩm trong shop.</p>
          <Link to="/seller/create-product" className="btn btn-outline">Tạo sản phẩm</Link>
          <Link to="/products" className="btn btn-ghost">Xem danh sách sản phẩm</Link>
        </div>
        <div className="card">
          <h3>Đơn hàng</h3>
          <p className="muted">Theo dõi hiệu suất đơn hàng và hủy đơn đang chờ.</p>
          <Link to="/orders" className="btn btn-outline">Xem đơn hàng</Link>
        </div>
      </div>
    </div>
  );
}
