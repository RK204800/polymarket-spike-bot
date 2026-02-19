# Polymarket Spike Reversal Bot

A high-frequency trading bot for Polymarket that detects price spikes and executes reversal trades. The bot monitors for sudden price movements and bets against the spike (expecting price to revert), while hedging with the opposite outcome.

## Strategy Overview

- **Monitor**: Watch price movements across your Polymarket positions
- **Detect**: Identify significant price spikes (configurable threshold, default 2%)
- **Trade**: When a spike is detected, bet against it (reversal strategy)
- **Hedge**: Simultaneously take the opposite position to reduce exposure
- **Exit**: Automatically exit at take profit (default 3%) or stop loss (default -2.5%)

## Requirements

- Python 3.8+
- MetaMask wallet with Polygon network
- USDC balance on Polygon
- Polymarket account with positions

## Quick Start

### 1. Clone and Install

```bash
git clone https://github.com/RK204800/polymarket-spike-bot.git
cd polymarket-spike-bot
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings
```

### 3. Run

```bash
python main.py
```

## Configuration

All settings are in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SPIKE_THRESHOLD` | 0.02 | Price movement % to trigger trade (2%) |
| `TAKE_PROFIT_PCT` | 0.03 | Profit target (3%) |
| `STOP_LOSS_PCT` | -0.025 | Stop loss threshold (-2.5%) |
| `TRADE_UNIT` | 3.0 | Trade size in USDC |
| `MAX_CONCURRENT_TRADES` | 3 | Max open positions |
| `MIN_LIQUIDITY` | 10.0 | Min liquidity to trade |
| `HOLDING_TIME_LIMIT` | 3600 | Max hold time in seconds |
| `COOLDOWN_PERIOD` | 30 | Seconds between trades |

### Wallet Setup

1. Create a MetaMask wallet
2. Add Polygon network
3. Get your proxy wallet address from Polymarket (Account → API)
4. Transfer USDC to your proxy wallet

### Discord Notifications

1. Create a Discord webhook in your server
2. Add the URL to `DISCORD_WEBHOOK_URL` in `.env`

## Deployment on Railway

### Option 1: One-Click Deploy

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new?template=https://github.com/RK204800/polymarket-spike-bot)

### Option 2: Manual Deploy

1. Connect Railway to your GitHub
2. Fork this repo
3. Create new Railway project from fork
4. Add environment variables in Railway dashboard
5. Deploy

### Railway Environment Variables

Set these in Railway:
- `PK` - Your private key
- `YOUR_PROXY_WALLET` - Polymarket proxy wallet
- `BOT_TRADER_ADDRESS` - Your wallet address
- `SPIKE_THRESHOLD` - 0.02
- `TAKE_PROFIT_PCT` - 0.03
- `STOP_LOSS_PCT` - -0.025
- `DISCORD_WEBHOOK_URL` - Your Discord webhook

## Safety Features

- ✅ Concurrent trade limits
- ✅ Take profit / stop loss automation
- ✅ Holding time limits
- ✅ Liquidity checks
- ✅ Balance verification
- ✅ USDC allowance management
- ✅ Graceful shutdown

## Disclaimer

⚠️ **Trading involves risk!** This bot is for educational purposes. 
- Never trade with funds you cannot afford to lose
- Always start with small trade sizes
- Monitor the bot initially
- The strategy is backtested at ~86% ROI but past performance doesn't guarantee future results

## License

MIT License

## Support

- Telegram: https://t.me/trust4120
- Issues: https://github.com/RK204800/polymarket-spike-bot/issues
