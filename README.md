# IGDM Pro — Instagram Automation SaaS

A production-ready Instagram Automation SaaS built with Django + SQLite + Meta's Instagram Graph API.

## Features

- **User Auth**: Register (email/password/mobile), Login, Logout
- **Instagram OAuth**: Connect multiple Business/Creator accounts (one IG account can be shared across multiple users)
- **Automations**: Comment → keyword match → automatic DM, Story reply → DM, DM auto-response
- **Webhook System**: Receive and process Instagram events in real-time
- **Dashboard**: Stats overview, contact management, account switching
- **Free Plan Limits**: 1 active automation, 3 keywords, 80-char DM, 1 link

---

## Quick Setup

### 1. Prerequisites
- Python 3.10+
- pip

### 2. Clone & Install

```bash
cd c:\Users\User\OneDrive\Documents\igdm
python -m venv venv
venv\Scripts\activate       # Windows
# source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
copy .env.example .env
```

Edit `.env` with your values:

```env
SECRET_KEY=your-unique-secret-key
DEBUG=True
BASE_URL=http://127.0.0.1:8000
INSTAGRAM_CLIENT_ID=your-meta-app-client-id
INSTAGRAM_CLIENT_SECRET=your-meta-app-client-secret
INSTAGRAM_WEBHOOK_VERIFY_TOKEN=igbot_secure_verify_token_2024_change_me
FERNET_KEY=<generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
```

### 4. Run Migrations & Create Superuser

```bash
python manage.py makemigrations accounts instagram automations webhooks dashboard
python manage.py migrate
python manage.py createsuperuser
```

### 5. Start Development Server

```bash
python manage.py runserver
```

Visit: http://127.0.0.1:8000/

---

## Meta App Setup Checklist

1. Go to [Meta for Developers](https://developers.facebook.com/)
2. Create a new app → select **Business** type
3. Add **Instagram** product
4. Configure **Instagram Business Login**:
   - Add redirect URI: `https://<YOUR_DOMAIN>/instagram/callback/`
   - Request permissions:
     - `instagram_business_basic`
     - `instagram_business_manage_messages`
     - `instagram_business_manage_comments`
     - `instagram_business_content_publish`
     - `instagram_business_manage_insights`
5. Configure **Webhooks**:
   - Callback URL: `https://<YOUR_DOMAIN>/webhook/instagram/`
   - Verify Token: (match `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` in `.env`)
   - Subscribe to: `comments`, `messages`
6. Copy App ID → `INSTAGRAM_CLIENT_ID`, App Secret → `INSTAGRAM_CLIENT_SECRET`

---

## DB Schema

```
┌──────────────┐     ┌────────────────────┐     ┌──────────────────────────┐
│   User       │     │ InstagramAccount   │     │ InstagramAccountUser     │
├──────────────┤     ├────────────────────┤     ├──────────────────────────┤
│ id           │◀────│ users (M2M)        │◀────│ user_id (FK → User)      │
│ email (uniq) │     │ ig_user_id (uniq)  │     │ instagram_account_id (FK)│
│ mobile       │     │ username           │     │ is_active                │
│ password     │     │ access_token_enc   │     │ is_owner                 │
└──────────────┘     │ token_expires_at   │     │ connected_at             │
                     └────────────────────┘     └──────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌──────────────┐  ┌────────────┐  ┌─────────────────┐
    │ Automation   │  │ Contact    │  │ WebhookEventLog │
    ├──────────────┤  ├────────────┤  ├─────────────────┤
    │ ig_account   │  │ ig_account │  │ ig_account      │
    │ created_by   │  │ automation │  │ event_type      │
    │ name         │  │ ig_user_id │  │ payload (JSON)  │
    │ template_type│  │ username   │  │ processed       │
    │ keywords     │  │ tag        │  │ error_message   │
    │ dm_message   │  │ dm_sent    │  │ received_at     │
    │ is_active    │  │ created_at │  └─────────────────┘
    │ is_paused    │  └────────────┘
    └──────────────┘
```

**Key relationship**: InstagramAccount ↔ User is **many-to-many** via `InstagramAccountUser`. One IG account can be used by multiple users, and one user can connect multiple IG accounts.

---

## API Routes

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/accounts/register/` | User registration |
| GET/POST | `/accounts/login/` | User login |
| GET | `/accounts/logout/` | Logout |
| GET | `/instagram/connect/` | Connect Instagram (OAuth start) |
| GET | `/instagram/callback/` | OAuth callback |
| GET | `/instagram/disconnect/<id>/` | Disconnect IG account |
| GET | `/instagram/switch/<id>/` | Switch active IG account |
| GET | `/dashboard/` | Dashboard home |
| GET | `/dashboard/contacts/` | Contacts list |
| GET | `/dashboard/settings/` | Settings |
| GET | `/automations/` | List automations |
| GET/POST | `/automations/create/` | Create automation |
| GET | `/automations/<id>/` | Automation detail |
| GET | `/automations/<id>/toggle/` | Activate/deactivate |
| POST | `/automations/<id>/delete/` | Delete automation |
| GET | `/automations/<id>/dry-run/` | Dry run simulation |
| GET/POST | `/webhook/instagram/` | Webhook endpoint |
| GET | `/admin/` | Django admin panel |

---

## Automation Flow

```
User creates automation
         │
         ▼
Commenter posts comment on IG
         │
         ▼
Instagram → Webhook (POST /webhook/instagram/)
         │
         ▼
Parse event → Find IG Account → Find active automation
         │
         ▼
Keyword match? ──No──▶ Skip
         │Yes
         ▼
Already DM'd this user? ──Yes──▶ Skip
         │No
         ▼
Send DM via Graph API (comment_id based)
         │
         ▼
Log Contact (username, tag, DM status)
```

---

## Webhook Testing (Local)

Use [ngrok](https://ngrok.com/) to expose your local server:

```bash
ngrok http 8000
```

Then configure the ngrok URL in Meta App webhooks.

Test verification:
```bash
curl "http://127.0.0.1:8000/webhook/instagram/?hub.mode=subscribe&hub.verify_token=igbot_secure_verify_token_2024_change_me&hub.challenge=test123"
# Should return: test123
```

Test comment event:
```bash
curl -X POST http://127.0.0.1:8000/webhook/instagram/ \
  -H "Content-Type: application/json" \
  -d '{"object":"instagram","entry":[{"id":"123","changes":[{"field":"comments","value":{"id":"c1","text":"I want the price","from":{"id":"456","username":"testuser"},"media":{"id":"m1"}}}]}]}'
```

---

## Production Deployment

1. Set `DEBUG=False` and configure `ALLOWED_HOSTS`
2. Set a strong `SECRET_KEY`
3. Generate and set `FERNET_KEY`
4. Configure `BASE_URL` to your production domain
5. Run `python manage.py collectstatic`
6. Use gunicorn: `gunicorn igdm.wsgi:application --bind 0.0.0.0:8000`
7. Configure nginx as reverse proxy
8. Set up SSL (required for Instagram webhooks)

---

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| Token expired | Long-lived token (60 days) expired | Reconnect via OAuth |
| Webhook verification failed | Verify token mismatch | Check `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` |
| DM send failed (400) | 24-hour window expired | Can only DM within 24h of user interaction |
| FERNET_KEY error | Missing or invalid key | Generate new key (see .env.example) |
| OAuth redirect mismatch | Callback URL doesn't match Meta App | Update redirect URI in Meta App settings |
