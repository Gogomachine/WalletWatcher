# Setup Scripts

## Telegram Authentication Setup

The whale discovery feature requires reading messages from the @solanawhaletracking Telegram channel. This requires one-time authentication.

### Prerequisites

1. Get Telegram API credentials from https://my.telegram.org:
   - Login with your phone number
   - Go to "API development tools"
   - Create an app to get `api_id` and `api_hash`

2. Add credentials to `.env`:
   ```bash
   TELEGRAM_API_ID=your_api_id_here
   TELEGRAM_API_HASH=your_api_hash_here
   ```

### Setup Process

Run the setup script:

```bash
python3 scripts/setup_telegram.py
```

The script will:
1. Prompt you to enter your phone number
2. Send a verification code to your Telegram app
3. Ask you to enter the code
4. Create a session file (`whale_parser.session`)
5. Verify access to @solanawhaletracking channel

### After Setup

Once the session file is created, the bot will automatically reuse it. You don't need to authenticate again unless:
- You delete the session file
- The session expires (rare)
- You move the bot to a different machine

### Troubleshooting

**"Session file not found" error:**
- Run `python3 scripts/setup_telegram.py` first

**"Could not verify channel access" warning:**
- Make sure @solanawhaletracking is accessible (not banned/restricted)
- Try joining the channel manually first

**Session expired:**
- Run the setup script again to re-authenticate
