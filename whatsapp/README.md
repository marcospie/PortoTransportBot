# WhatsApp Bot - Porto Transport

WhatsApp alternative for the Porto Transport Bot.

## Setup

1. Create a [Meta Business Account](https://business.facebook.com/)
2. Create a WhatsApp Business App in [Meta Developer Portal](https://developers.facebook.com/)
3. Get your credentials from the WhatsApp section:
   - **WHATSAPP_TOKEN**: Permanent access token
   - **WHATSAPP_PHONE_ID**: Phone number ID
4. Add to your `.env` file:
   ```
   WHATSAPP_TOKEN=your_token
   WHATSAPP_PHONE_ID=your_phone_id
   WHATSAPP_VERIFY_TOKEN=porto-transport-bot
   ```
5. Deploy and configure the webhook URL:
   ```
   https://your-domain/webhook
   ```
6. Subscribe to `messages` webhook events

## Run

```bash
python -m whatsapp.app
```

Or with Docker:
```bash
docker-compose up whatsapp
```

## Features

- Search bus stops by name or code
- Real-time bus arrivals
- Metro station schedules
- Location-based nearby transport
- Interactive menus and lists
