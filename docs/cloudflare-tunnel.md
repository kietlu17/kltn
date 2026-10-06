# Cloudflare Tunnel for the local backend

The frontend can run on Vercel while the backend remains on the local Docker
Compose network. A remotely managed Cloudflare Tunnel publishes the API
gateway without opening an inbound port on the router.

## 1. Create the tunnel

In Cloudflare, create a remotely managed tunnel and add these public
hostnames:

| Public hostname | Origin service | Purpose |
| --- | --- | --- |
| `api.example.com` | `http://api-gateway:3000` | Frontend API and product images |
| `sepay-webhook.example.com` | `http://api-gateway:3000` | SePay callback only |

`api-gateway` is the Docker Compose service name. Do not configure the origin
as `localhost:3000`, because `localhost` inside the `cloudflared` container is
the tunnel container itself.

Copy the tunnel token into the ignored root `.env` file:

```dotenv
CLOUDFLARE_TUNNEL_TOKEN=<tunnel-token>
PRODUCT_IMAGE_PUBLIC_BASE_URL=https://api.example.com/uploads
```

Do not commit the tunnel token.

The connector will not establish a tunnel when this value is empty. Add the
token before starting the `cloudflared` service.

## 2. Start and verify the connector

```powershell
docker compose up -d --build
docker compose logs -f cloudflared
```

Verify that the public hostname reaches the gateway:

```powershell
Invoke-RestMethod https://api.example.com/assistant/health
```

Configure the Vercel frontend build variables and redeploy it:

```dotenv
VITE_API_BASE_URL=https://api.example.com
VITE_PRODUCT_IMAGE_BASE_URL=https://api.example.com/uploads
```

## 3. Configure the SePay webhook

Set the callback URL in the SePay dashboard to the exact public endpoint:

```text
https://sepay-webhook.example.com/payments/sepay/webhook
```

The callback must use `POST` and preserve the authorization header expected by
the payment gateway:

```text
Authorization: Apikey <SEPAY_WEBHOOK_API_KEY>
Content-Type: application/json
```

The API gateway deliberately treats only `POST /payments/sepay/webhook` as a
public route. Other `/payments/sepay/*` routes continue to require the
application JWT and roles.

Do not place Cloudflare Access login, a JavaScript challenge, or an interactive
bot challenge in front of the webhook hostname. SePay cannot complete an
interactive challenge. If Cloudflare WAF rules are enabled, create a narrowly
scoped skip rule for the webhook hostname and exact path while retaining the
application-level `SEPAY_WEBHOOK_API_KEY` check.

Suggested Cloudflare rule expression:

```text
(http.host eq "sepay-webhook.example.com" and
 http.request.method eq "POST" and
 http.request.uri.path eq "/payments/sepay/webhook")
```

Do not rewrite or strip the `/payments/sepay` prefix in the tunnel route.

## 4. Test the webhook path

First verify that a request without the SePay API key reaches the application
and is rejected there, rather than by Cloudflare:

```powershell
try {
  Invoke-RestMethod `
    -Method Post `
    -Uri https://sepay-webhook.example.com/payments/sepay/webhook `
    -ContentType 'application/json' `
    -Body '{"id":"cloudflare-connectivity-test"}'
} catch {
  $_.Exception.Response.StatusCode.value__
}
```

When `SEPAY_WEBHOOK_API_KEY` is configured, the expected result is HTTP `401`
with `Unauthorized webhook`. If the key is missing, the application fails
closed with HTTP `503` and `Missing SEPAY_WEBHOOK_API_KEY`; it does not accept
the payload. A Cloudflare-branded HTML response, `403`, or a redirect to an
Access login page means the Cloudflare policy is blocking the callback before
it reaches the application.

For a full end-to-end test, create a pending SePay payment request and send a
signed test payload with a unique transaction `id` and the matching request
code. Reusing the transaction `id` exercises the idempotency path and should be
reported as a duplicate rather than crediting the payment twice.
