import { useToast } from '../context/ToastContext.jsx';

export default function Toast() {
  const { toast } = useToast();
  if (!toast) return null;

  return (
    <div className={`toast toast-${toast.type}`}>
      {toast.message}
    </div>
  );
}


