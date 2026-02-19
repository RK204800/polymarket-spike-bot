"""
Polymarket Spike Reversal Bot
=============================
A high-frequency trading bot that detects price spikes and trades reversals.
Strategy: Monitor price spikes, bet against the spike (reversal), hedge with opposite position.

Configuration via environment variables - ready for Railway deployment.
"""

import os
import time
import json
import requests
import logging
import threading
import signal
import sys
from datetime import datetime
from dotenv import load_dotenv
from web3 import Web3
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL
from typing import Dict, List, Optional, Any
from collections import deque, defaultdict
from threading import Lock, Event
from dataclasses import dataclass
from enum import Enum

# ============================================================
# CONFIGURATION - All configurable via environment variables
# ============================================================

load_dotenv(".env")

# --- Trading Parameters (with sensible defaults) ---
SPIKE_THRESHOLD = float(os.getenv("SPIKE_THRESHOLD", "0.02"))  # 2% price spike triggers trade
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.03"))   # 3% profit target
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "-0.025"))    # -2.5% stop loss
TRADE_UNIT = float(os.getenv("TRADE_UNIT", "3.0"))             # Base trade size in USDC
MAX_CONCURRENT_TRADES = int(os.getenv("MAX_CONCURRENT_TRADES", "3"))
MIN_LIQUIDITY = float(os.getenv("MIN_LIQUIDITY", "10.0"))      # Min liquidity to trade
SLIPPAGE_TOLERANCE = float(os.getenv("SLIPPAGE_TOLERANCE", "0.02"))
HOLDING_TIME_LIMIT = int(os.getenv("HOLDING_TIME_LIMIT", "3600"))  # Max hold time in seconds
PRICE_HISTORY_SIZE = int(os.getenv("PRICE_HISTORY_SIZE", "100"))
COOLDOWN_PERIOD = int(os.getenv("COOLDOWN_PERIOD", "30"))       # Seconds between trades

# --- Wallet & Contract Configuration ---
WEB3_PROVIDER = os.getenv("WEB3_PROVIDER", "https://polygon-rpc.com")
PRIVATE_KEY = os.getenv("PK", "")
YOUR_PROXY_WALLET = os.getenv("YOUR_PROXY_WALLET", "")
BOT_TRADER_ADDRESS = os.getenv("BOT_TRADER_ADDRESS", "")
USDC_CONTRACT_ADDRESS = os.getenv("USDC_CONTRACT_ADDRESS", "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
POLYMARKET_SETTLEMENT_CONTRACT = os.getenv("POLYMARKET_SETTLEMENT_CONTRACT", "0x56C79347e95530c01A2FC76E732f9566dA16E113")

# --- Discord/Callback Notifications ---
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")       # Discord webhook for notifications
CALLBACK_URL = os.getenv("CALLBACK_URL", "")                     # Generic callback URL (optional)

# --- Constants ---
MAX_RETRIES = 3
API_TIMEOUT = 10

# Validate required config
required = [PRIVATE_KEY, YOUR_PROXY_WALLET, BOT_TRADER_ADDRESS]
if not all(required):
    raise ValueError(f"Missing required config: PK, YOUR_PROXY_WALLET, BOT_TRADER_ADDRESS")

# Initialize Web3
web3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER))
YOUR_PROXY_WALLET = Web3.to_checksum_address(YOUR_PROXY_WALLET)
BOT_TRADER_ADDRESS = Web3.to_checksum_address(BOT_TRADER_ADDRESS)

# ============================================================
# LOGGING SETUP
# ============================================================

def setup_logging() -> logging.Logger:
    """Setup logging with file and console handlers."""
    os.makedirs('logs', exist_ok=True)
    
    logger = logging.getLogger('polymarket_bot')
    logger.setLevel(logging.INFO)
    logger.handlers = []
    
    # File formatter
    file_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console formatter with colors
    import colorlog
    console_formatter = colorlog.ColoredFormatter(
        '%(log_color)s%(asctime)s | %(levelname)-8s | %(message)s%(reset)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        log_colors={
            'DEBUG': 'cyan', 'INFO': 'green', 'WARNING': 'yellow',
            'ERROR': 'red', 'CRITICAL': 'red,bg_white'
        }
    )
    
    # File handler
    file_handler = logging.FileHandler('logs/polymarket_bot.log')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

# ============================================================
# NOTIFICATIONS
# ============================================================

def send_notification(message: str, embed: bool = True) -> None:
    """Send notification to Discord webhook and/or callback URL."""
    logger.info(f"📢 Notification: {message}")
    
    # Discord webhook
    if DISCORD_WEBHOOK_URL:
        try:
            payload = {"content": message} if not embed else {
                "embeds": [{
                    "title": "🤖 Polymarket Spike Bot",
                    "description": message,
                    "timestamp": datetime.utcnow().isoformat(),
                    "color": 3066993  # Green
                }]
            }
            requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        except Exception as e:
            logger.warning(f"Failed to send Discord notification: {e}")
    
    # Generic callback
    if CALLBACK_URL:
        try:
            requests.post(CALLBACK_URL, json={"message": message}, timeout=5)
        except Exception as e:
            logger.warning(f"Failed to send callback: {e}")

# ============================================================
# DATA TYPES
# ============================================================

@dataclass
class TradeInfo:
    entry_price: float
    entry_time: float
    amount: float

@dataclass
class PositionInfo:
    eventslug: str
    outcome: str
    asset: str
    avg_price: float
    shares: float
    current_price: float

class TradeType(Enum):
    BUY = "buy"
    SELL = "sell"

# ============================================================
# STATE MANAGEMENT
# ============================================================

class BotState:
    def __init__(self):
        self._lock = Lock()
        self._price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=PRICE_HISTORY_SIZE))
        self._active_trades: Dict[str, TradeInfo] = {}
        self._positions: Dict[str, List[PositionInfo]] = {}
        self._asset_pairs: Dict[str, str] = {}
        self._recent_trades: Dict[str, Dict[str, Optional[float]]] = {}
        self._shutdown_event = Event()
        
    def shutdown(self):
        self._shutdown_event.set()
        
    def is_shutdown(self) -> bool:
        return self._shutdown_event.is_set()
    
    @property
    def price_history(self) -> Dict[str, deque]:
        with self._lock:
            return dict(self._price_history)
    
    def add_price(self, asset_id: str, timestamp: float, price: float, eventslug: str, outcome: str):
        with self._lock:
            self._price_history[asset_id].append((timestamp, price, eventslug, outcome))
    
    @property
    def active_trades(self) -> Dict[str, TradeInfo]:
        with self._lock:
            return dict(self._active_trades)
    
    def add_active_trade(self, asset_id: str, trade: TradeInfo):
        with self._lock:
            self._active_trades[asset_id] = trade
    
    def remove_active_trade(self, asset_id: str):
        with self._lock:
            self._active_trades.pop(asset_id, None)
    
    @property
    def positions(self) -> Dict[str, List[PositionInfo]]:
        with self._lock:
            return dict(self._positions)
    
    def update_positions(self, new_positions: Dict[str, List[PositionInfo]]):
        with self._lock:
            self._positions = new_positions
    
    def add_asset_pair(self, asset1: str, asset2: str):
        with self._lock:
            self._asset_pairs[asset1] = asset2
            self._asset_pairs[asset2] = asset1
    
    def get_asset_pair(self, asset_id: str) -> Optional[str]:
        with self._lock:
            return self._asset_pairs.get(asset_id)
    
    def update_recent_trade(self, asset_id: str, trade_type: TradeType):
        with self._lock:
            if asset_id not in self._recent_trades:
                self._recent_trades[asset_id] = {"buy": None, "sell": None}
            self._recent_trades[asset_id][trade_type.value] = time.time()
    
    def is_recently_traded(self, asset_id: str, trade_type: TradeType) -> bool:
        with self._lock:
            if asset_id not in self._recent_trades:
                return False
            last_trade = self._recent_trades[asset_id][trade_type.value]
            if last_trade is None:
                return False
            return (time.time() - last_trade) < COOLDOWN_PERIOD

state = BotState()

# ============================================================
# CLOB CLIENT SETUP
# ============================================================

def initialize_client() -> ClobClient:
    """Initialize the Polymarket CLOB client."""
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=PRIVATE_KEY,
        chain_id=137,
        signature_type=2,
        funder=YOUR_PROXY_WALLET
    )
    api_creds = client.create_or_derive_api_creds()
    client.set_api_creds(api_creds)
    return client

client = initialize_client()

# ============================================================
# TRADING FUNCTIONS
# ============================================================

def fetch_positions() -> Dict[str, List[PositionInfo]]:
    """Fetch current positions from Polymarket API."""
    url = f"https://data-api.polymarket.com/positions?user={YOUR_PROXY_WALLET}"
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, timeout=API_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                return {}
                
            positions: Dict[str, List[PositionInfo]] = {}
            for pos in data:
                event_id = pos.get("conditionId") or pos.get("eventId") or pos.get("marketId")
                if not event_id:
                    continue
                    
                if event_id not in positions:
                    positions[event_id] = []
                    
                try:
                    position_info = PositionInfo(
                        eventslug=pos.get("eventSlug", ""),
                        outcome=pos.get("outcome", ""),
                        asset=pos.get("asset", ""),
                        avg_price=float(pos.get("avgPrice", 0)),
                        shares=float(pos.get("size", 0)),
                        current_price=float(pos.get("curPrice", 0))
                    )
                    positions[event_id].append(position_info)
                except (ValueError, TypeError):
                    continue
                    
            return positions
            
        except Exception as e:
            logger.error(f"Error fetching positions (attempt {attempt+1}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
    
    return {}

def get_order_book(asset: str) -> Optional[Dict[str, Any]]:
    """Get order book data for an asset."""
    try:
        order = client.get_order_book(asset)
        
        if order.asks:
            return {
                "side": "buy",
                "price": order.asks[-1].price,
                "size": order.asks[-1].size
            }
        elif order.bids:
            return {
                "side": "sell", 
                "price": order.bids[-1].price,
                "size": order.bids[-1].size
            }
        return None
    except Exception as e:
        logger.error(f"Error getting order book for {asset}: {e}")
        return None

def check_usdc_balance() -> float:
    """Check USDC balance in wallet."""
    try:
        usdc_contract = web3.eth.contract(
            address=USDC_CONTRACT_ADDRESS,
            abi=[{"constant":True,"inputs":[{"name":"account","type":"address"}],
                  "name":"balanceOf","outputs":[{"name":"","type":"uint256"}],
                  "stateMutability":"view","type":"function"}]
        )
        return usdc_contract.functions.balanceOf(YOUR_PROXY_WALLET).call() / 10**6
    except Exception as e:
        logger.error(f"Error checking USDC balance: {e}")
        return 0

def ensure_allowance(amount: float) -> bool:
    """Ensure USDC allowance for trading."""
    try:
        contract = web3.eth.contract(
            address=USDC_CONTRACT_ADDRESS,
            abi=[
                {"constant":True,"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
                 "name":"allowance","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
                {"constant":False,"inputs":[{"name":"spender","type":"address"},{"name":"value","type":"uint256"}],
                 "name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"}
            ]
        )
        
        current_allowance = contract.functions.allowance(BOT_TRADER_ADDRESS, POLYMARKET_SETTLEMENT_CONTRACT).call()
        required = int(amount * 1.1 * 10**6)
        
        if current_allowance >= required:
            return True
        
        # Approve
        txn = contract.functions.approve(POLYMARKET_SETTLEMENT_CONTRACT, required).build_transaction({
            "from": BOT_TRADER_ADDRESS,
            "gas": 200000,
            "gasPrice": web3.eth.gas_price,
            "nonce": web3.eth.get_transaction_count(BOT_TRADER_ADDRESS),
            "chainId": 137
        })
        
        signed = web3.eth.account.sign_transaction(txn, private_key=PRIVATE_KEY)
        tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
        web3.eth.wait_for_transaction_receipt(tx_hash)
        
        logger.info(f"USDC allowance updated")
        return True
        
    except Exception as e:
        logger.error(f"Error ensuring allowance: {e}")
        return False

def place_order(asset: str, side: str, reason: str) -> bool:
    """Place a buy or sell order."""
    try:
        # Check concurrent trades limit
        active = state.active_trades
        if len(active) >= MAX_CONCURRENT_TRADES:
            logger.warning(f"Max concurrent trades reached ({len(active)}/{MAX_CONCURRENT_TRADES})")
            return False
        
        # Get order book
        ob = get_order_book(asset)
        if not ob:
            logger.warning(f"No order book data for {asset}")
            return False
        
        price = ob["price"]
        size = ob["size"]
        
        # Check liquidity
        value = size * price
        if value < MIN_LIQUIDITY:
            logger.warning(f"Insufficient liquidity for {asset}: ${value:.2f} < ${MIN_LIQUIDITY}")
            return False
        
        # Calculate trade amount
        amount = min(TRADE_UNIT, value)
        
        # Check balance
        balance = check_usdc_balance()
        if balance < amount:
            logger.warning(f"Insufficient USDC: ${balance:.2f} < ${amount:.2f}")
            return False
        
        if not ensure_allowance(amount):
            return False
        
        # Place order
        side_enum = BUY if side == "buy" else SELL
        order_args = MarketOrderArgs(
            token_id=str(asset),
            amount=float(amount),
            side=side_enum,
        )
        
        signed_order = client.create_market_order(order_args)
        response = client.post_order(signed_order, OrderType.FOK)
        
        if response.get("success"):
            filled = response.get("data", {}).get("filledAmount", amount)
            emoji = "🟢" if side == "buy" else "🔴"
            msg = f"{emoji} [{reason}] {side.upper()} {filled:.4f} of {asset} @ ${price:.4f}"
            logger.info(msg)
            send_notification(msg)
            
            # Track the trade
            state.update_recent_trade(asset, TradeType.BUY if side == "buy" else TradeType.SELL)
            
            if side == "buy":
                state.add_active_trade(asset, TradeInfo(price, time.time(), amount))
            else:
                state.remove_active_trade(asset)
                
            return True
        else:
            logger.error(f"Order failed: {response.get('error', 'Unknown error')}")
            return False
            
    except Exception as e:
        logger.error(f"Error placing {side} order for {asset}: {e}")
        return False

def find_position(positions: Dict[str, List[PositionInfo]], asset_id: str) -> Optional[PositionInfo]:
    """Find a position by asset ID."""
    for event_positions in positions.values():
        for pos in event_positions:
            if pos.asset == asset_id:
                return pos
    return None

# ============================================================
# MAIN LOOPS
# ============================================================

def update_prices():
    """Background thread: fetch and update prices."""
    last_log = time.time()
    
    while not state.is_shutdown():
        try:
            positions = fetch_positions()
            
            if not positions:
                time.sleep(5)
                continue
            
            state.update_positions(positions)
            
            # Initialize asset pairs and track prices
            for event_id, assets in positions.items():
                if len(assets) >= 2:
                    state.add_asset_pair(assets[0].asset, assets[1].asset)
                
                for asset in assets:
                    if asset.asset and asset.current_price > 0:
                        state.add_price(asset.asset, time.time(), asset.current_price, 
                                       asset.eventslug, asset.outcome)
            
            # Log prices periodically
            if time.time() - last_log >= 30:
                logger.info(f"📊 Tracking {len(state.price_history)} assets")
                last_log = time.time()
                
        except Exception as e:
            logger.error(f"Error in price update: {e}")
            time.sleep(5)

def detect_spikes():
    """Background thread: detect price spikes and execute trades."""
    last_log = time.time()
    scan_count = 0
    
    while not state.is_shutdown():
        try:
            scan_count += 1
            positions = state.positions
            
            if time.time() - last_log >= 30:
                logger.info(f"🔍 Scanning markets | Scans: {scan_count} | Active: {len(positions)}")
                last_log = time.time()
            
            for asset_id, history in state.price_history.items():
                if len(history) < 2:
                    continue
                    
                old_price = history[0][1]
                new_price = history[-1][1]
                
                if old_price == 0 or new_price == 0:
                    continue
                
                delta = (new_price - old_price) / old_price
                
                # Skip if no significant spike
                if abs(delta) < SPIKE_THRESHOLD:
                    continue
                
                # Skip extreme prices
                if new_price < 0.20 or new_price > 0.80:
                    continue
                
                # Get opposite asset
                opposite = state.get_asset_pair(asset_id)
                if not opposite:
                    continue
                
                # Determine action based on spike direction (reversal strategy)
                if delta > 0 and not state.is_recently_traded(asset_id, TradeType.BUY):
                    # Price spiked up - bet against it (sell the spike)
                    logger.info(f"🟨 Spike detected | {asset_id} | Δ: {delta:.2%} | ${new_price:.4f}")
                    logger.info(f"🔴 SELL signal | {asset_id}")
                    
                    if place_order(asset_id, "sell", "Spike reversal"):
                        # Hedge with opposite
                        place_order(opposite, "buy", "Hedge")
                        
                elif delta < 0 and not state.is_recently_traded(asset_id, TradeType.SELL):
                    # Price spiked down - bet against it (buy the dip)
                    logger.info(f"🟨 Spike detected | {asset_id} | Δ: {delta:.2%} | ${new_price:.4f}")
                    logger.info(f"🟢 BUY signal | {asset_id}")
                    
                    if place_order(asset_id, "buy", "Spike reversal"):
                        # Hedge with opposite
                        place_order(opposite, "sell", "Hedge")
                        
        except Exception as e:
            logger.error(f"Error in spike detection: {e}")
            time.sleep(1)

def check_exits():
    """Background thread: check take profit and stop loss."""
    while not state.is_shutdown():
        try:
            active_trades = state.active_trades
            positions = state.positions
            
            for asset_id, trade in active_trades.items():
                position = find_position(positions, asset_id)
                if not position:
                    continue
                
                current_price = position.current_price
                avg_price = trade.entry_price
                shares = position.shares
                
                if shares < 1:
                    continue
                
                pct_change = (current_price - avg_price) / avg_price
                pnl = (current_price - avg_price) * shares
                
                now = time.time()
                
                # Check holding time limit
                if now - trade.entry_time > HOLDING_TIME_LIMIT:
                    logger.info(f"⏰ Time limit hit | {asset_id} | Held: {now - trade.entry_time:.0f}s")
                    if place_order(asset_id, "sell", "Time limit"):
                        state.remove_active_trade(asset_id)
                    continue
                
                # Check take profit
                if pct_change >= TAKE_PROFIT_PCT:
                    logger.info(f"🎯 Take profit | {asset_id} | +{pct_change:.2%} | ${pnl:.2f}")
                    if place_order(asset_id, "sell", "Take profit"):
                        state.remove_active_trade(asset_id)
                    continue
                
                # Check stop loss
                if pct_change <= STOP_LOSS_PCT:
                    logger.info(f"🔴 Stop loss | {asset_id} | {pct_change:.2%} | ${pnl:.2f}")
                    if place_order(asset_id, "sell", "Stop loss"):
                        state.remove_active_trade(asset_id)
                        
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"Error in exit check: {e}")
            time.sleep(1)

# ============================================================
# MAIN
# ============================================================

def signal_handler(sig, frame):
    """Handle graceful shutdown."""
    logger.info("Shutting down...")
    state.shutdown()
    sys.exit(0)

def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("🤖 Polymarket Spike Reversal Bot Starting")
    logger.info(f"   Spike Threshold: {SPIKE_THRESHOLD:.1%}")
    logger.info(f"   Take Profit: {TAKE_PROFIT_PCT:.1%}")
    logger.info(f"   Stop Loss: {STOP_LOSS_PCT:.1%}")
    logger.info(f"   Trade Unit: ${TRADE_UNIT}")
    logger.info(f"   Max Concurrent: {MAX_CONCURRENT_TRADES}")
    logger.info("=" * 60)
    
    send_notification("🤖 Bot started! Monitoring for spike reversals...")
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start background threads
    threads = [
        threading.Thread(target=update_prices, daemon=True, name="prices"),
        threading.Thread(target=detect_spikes, daemon=True, name="detect"),
        threading.Thread(target=check_exits, daemon=True, name="exits"),
    ]
    
    for t in threads:
        t.start()
    
    # Keep main thread alive
    while not state.is_shutdown():
        time.sleep(1)

if __name__ == "__main__":
    main()
