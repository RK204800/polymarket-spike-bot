# Polymarket Spike Reversal Bot

A trading bot for Polymarket that detects price spikes and executes reversal trades. When price spikes suddenly, bet against it expecting reversion.

## Strategy

- **Monitor**: Watch price movements in real-time
- **Detect**: Identify spikes (default: 2%+ price movement)
- **Trade**: Bet against the spike (reversal)
- **Exit**: Auto-exit at 3% profit or -2.5% stop loss

## How to Get Started

### Step 1: Get Polymarket Keys
1. Go to **polymarket.com/settings?tab=builder**
2. Generate API keys
3. Copy your **proxy wallet address**

### Step 2: Get Wallet Ready
- MetaMask with Polygon network
- USDC on Polygon (for trading)
- Your wallet address: `0x0dA4B59a19A59b6d9B8c68FaB8b5eF816C3e4191`

### Step 3: Deploy to Railway

**Quickest way:**

1. Go to https://railway.app
2. Sign up with GitHub
3. Click **New Project** → **Deploy from GitHub repo**
4. Select `RK204800/polymarket-spike-bot`
5. Add these environment variables:

| Variable | Value |
|----------|-------|
| `PRIVATE_KEY` | your MetaMask private key (starts with 0x...) |
| `YOUR_PROXY_WALLET` | from polymarket.com/settings?tab=builder |
| `BOT_TRADER_ADDRESS` | `0x0dA4B59a19A59b6d9B8c68FaB8b5eF816C3e4191` |
| `SPIKE_THRESHOLD` | `0.02` |
| `TAKE_PROFIT_PCT` | `0.03` |
| `STOP_LOSS_PCT` | `-0.025` |
| `TRADE_UNIT` | `3.0` |

6. Click **Deploy**

### Step 4: Run in Test Mode

Start with small amounts (`TRADE_UNIT=1` or `2`) to verify it works before scaling up.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SPIKE_THRESHOLD` | 0.02 | 2% price spike triggers trade |
| `TAKE_PROFIT_PCT` | 0.03 | 3% profit target |
| `STOP_LOSS_PCT` | -0.025 | -2.5% stop loss |
| `TRADE_UNIT` | 3.0 | Trade size in USDC |
| `MAX_CONCURRENT_TRADES` | 3 | Max open positions |
| `MIN_LIQUIDITY` | 10.0 | Min liquidity to trade |
| `DISCORD_WEBHOOK_URL` | (optional) | Discord notifications |

## Local Development

```bash
git clone https://github.com/RK204800/polymarket-spike-bot.git
cd polymarket-spike-bot
cp .env.example .env
# Edit .env with your keys
pip install -r requirements.txt
python main.py
```

## Safety Features

- ✅ Max concurrent trades limit
- ✅ Auto take profit / stop loss
- ✅ Max holding time (1 hour default)
- ✅ Liquidity checks before trading
- ✅ Graceful shutdown

## Disclaimer

⚠️ **Trading involves risk!** Start with small amounts. This is not financial advice.

---

**Note:** The `.env` file is gitignored — your keys won't be committed.
