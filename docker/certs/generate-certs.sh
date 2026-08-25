#!/bin/sh
set -eu

CERT_ROOT=/certs
CA_DIR="$CERT_ROOT/ca"
mkdir -p "$CA_DIR"

if [ ! -f "$CA_DIR/ca.key" ] || [ ! -f "$CA_DIR/ca.crt" ]; then
  openssl genrsa -out "$CA_DIR/ca.key" 4096
  openssl req -x509 -new -nodes -key "$CA_DIR/ca.key" -sha256 -days 3650 -out "$CA_DIR/ca.crt" -subj "/CN=ecommerce-local-ca"
fi

SERVICES="api-gateway auth-service user-service shop-service product-service cart-service order-service inventory-service voucher-service review-service payment-service wallet-service payment-gateway chat-service livestream-service ai-cohost-service"

for svc in $SERVICES; do
  svc_dir="$CERT_ROOT/$svc"
  mkdir -p "$svc_dir"

  if [ -f "$svc_dir/tls.key" ] && [ -f "$svc_dir/tls.crt" ]; then
    continue
  fi

  openssl genrsa -out "$svc_dir/tls.key" 2048

  cat > "$svc_dir/openssl.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = $svc

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = $svc
DNS.2 = localhost
EOF

  openssl req -new -key "$svc_dir/tls.key" -out "$svc_dir/tls.csr" -config "$svc_dir/openssl.cnf"
  openssl x509 -req \
    -in "$svc_dir/tls.csr" \
    -CA "$CA_DIR/ca.crt" \
    -CAkey "$CA_DIR/ca.key" \
    -CAcreateserial \
    -out "$svc_dir/tls.crt" \
    -days 825 \
    -sha256 \
    -extensions v3_req \
    -extfile "$svc_dir/openssl.cnf"

  cp "$CA_DIR/ca.crt" "$svc_dir/ca.crt"
  rm -f "$svc_dir/tls.csr" "$svc_dir/openssl.cnf"
done

echo "Certificates generated in $CERT_ROOT"
