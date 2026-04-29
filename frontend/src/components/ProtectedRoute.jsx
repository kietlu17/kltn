import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';

export default function ProtectedRoute({ allowedRoles, redirectTo, children }) {
  const { user, role } = useAuth();
  let fallback = '/login';
  if (allowedRoles && allowedRoles.includes('admin')) fallback = '/admin/login';
  else if (allowedRoles && allowedRoles.includes('seller')) fallback = '/seller/login';
  if (redirectTo) fallback = redirectTo;

  if (!user) {
    return <Navigate to={fallback} replace />;
  }

  if (allowedRoles && !allowedRoles.includes(role)) {
    return <Navigate to={fallback} replace />;
  }

  return children;
}


