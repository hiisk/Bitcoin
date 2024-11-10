import requests
import pandas as pd
import time
from pybit.unified_trading import HTTP
import datetime
import math

# Bybit API 설정
TELEGRAM_BOT_TOKEN = ''
TELEGRAM_CHAT_ID = ''

# Pybit 세션 설정
session = HTTP(
    testnet=False,
    api_key="", #API KEY입력
    api_secret="", #API SECRET 입력
)

# Bybit v5에서 1분봉 데이터 가져오기
def fetch_kline_data(symbol, interval='1', limit=200):
    try:
        response = session.get_kline(symbol=symbol, interval=interval, limit=limit)
        data = response['result']['list']

        # DataFrame으로 변환
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'qty','volume'])
        df[['open', 'high', 'low', 'close', 'qty', 'volume']] = df[['open', 'high', 'low', 'close', 'qty', 'volume']].apply(pd.to_numeric, errors='coerce')
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df[['timestamp', 'open', 'high', 'low', 'close']].dropna()
    except Exception as e:
        notify(f"Error fetching kline data: {str(e)}")
        return None

# 사용 가능한 USDT 잔고 확인
def get_available_balance():
    try:
        response = session.get_wallet_balance(accountType="Unified",)  # 선물 계정 잔고 조회
        for i in response['result']['list'][0]['coin']:
            if i['coin'] == 'USDT':
                return float(i['walletBalance'])
    except Exception as e:
        notify(f"Error fetching account balance: {str(e)}")
        return 0.0

# 리미트 오더 주문 실행
def place_limit_order(symbol, side, price, qty):
    try:
        response = session.place_order(
            symbol=symbol,
            category="linear",
            side='Buy' if side == 'buy' else 'Sell',
            order_type='Limit',
            qty=qty,
            price=price,
            isLeverage=1,
            stopLoss = math.floor(price*0.995 * 10)/10,
            takeProfit = math.floor(price*1.005 * 10)/10,
            time_in_force='GoodTillCancel'
        )
        if response['ret_code'] == 0:
            order_id = response['result']['orderId']
            notify(f"{side} limit order placed: Price: {price}, Amount: {qty}")
            return order_id  # 주문 ID 반환
        else:
            notify(f"Order failed: {response['ret_msg']}")
            return None
    except Exception as e:
        notify(f"Error placing order: {str(e)}")
        return None

# 주문 취소
def cancel_order(order_id):
    try:
        response = session.cancel_order(orderId=order_id)
        return response['ret_code'] == 0
    except Exception as e:
        notify(f"Error canceling order: {str(e)}")
        return False

# Telegram 메시지 전송 및 출력
def notify(message):
    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"TPrint: [{current_time}] {message}")
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    params = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': f'[{current_time}] {message}'
    }
    try:
        requests.post(url, params=params)
    except Exception as e:
        print(f"Error sending Telegram message: {str(e)}")

# 이동평균선 계산
def calculate_moving_average(data, window):
    return data['close'].rolling(window=window).mean()

# RSI 계산 (20봉 기준)
def calculate_rsi(data, window=20):
    delta = data['close'].iloc[::-1].diff()
    gain = delta.clip(lower=0).rolling(window=window).mean()
    loss = -delta.clip(upper=0).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# ATR 계산 (20봉 기준)
def calculate_atr(data, window=20):
    high_low = data['high'].iloc[::-1] - data['low'].iloc[::-1]
    high_prev_close = (data['high'].iloc[::-1] - data['close'].iloc[::-1].shift()).abs()
    low_prev_close = (data['low'].iloc[::-1] - data['close'].iloc[::-1].shift()).abs()
    true_range = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
    return true_range.rolling(window=window).mean()

# 거래 실행
def execute_trade(order_type, price):
    available_balance = get_available_balance()
    if available_balance == 0.0:
        return None
    amount = math.floor(available_balance * 0.5 / price * 1000) / 1000

    if order_type == 'buy':
        order_id = place_limit_order('BTCUSDT', 'buy', price - 1, amount)
        if order_id:
            return order_id, price - 1  # 주문 ID와 주문 가격 반환
    elif order_type == 'sell':
        order_id = place_limit_order('BTCUSDT', 'sell', price + 1, amount)
        if order_id:
            return order_id, price + 1  # 주문 ID와 주문 가격 반환
    return None, None

# 주문 수정 함수 (0.2% 이상 상승 시 스탑로스 설정)
def amend_stop_loss(order_id, new_price):
    try:
        response = session.amend_order(orderId=order_id, stopLossPrice=new_price)
        if response['ret_code'] == 0:
            notify(f"Stop loss amended for order {order_id} to {new_price}")
        else:
            notify(f"Failed to amend stop loss for order {order_id}: {response['ret_msg']}")
    except Exception as e:
        notify(f"Error amending stop loss for order {order_id}: {str(e)}")

# 5분 내 체결되지 않은 주문 취소 함수
def cancel_unfilled_order_after_timeout(order_id, timeout=300):
    start_time = time.time()
    while True:
        time_elapsed = time.time() - start_time
        order_status = session.get_order_history(orderId=order_id)
        if order_status['result']['list'][0]['order_status'] == 'Filled':
            notify(f"Order {order_id} filled within {time_elapsed:.2f} seconds.")
            break
        if time_elapsed > timeout:
            cancel_successful = cancel_order(order_id)
            if cancel_successful:
                notify(f"Order {order_id} canceled after {timeout} seconds due to no fill.")
            else:
                notify(f"Failed to cancel order {order_id} after {timeout} seconds.")
            break
        time.sleep(1)  # 1초마다 확인

# 매매 전략
def trading_strategy():
    symbol = 'BTCUSDT'
    long_position_flag = False
    short_position_flag = False
    long_confirmation_count = 0
    short_confirmation_count = 0
    long_exit_confirmation_count = 0
    short_exit_confirmation_count = 0
    confirmation_threshold = 12
    long_order_id, short_order_id = None, None
    long_entry_balance, short_entry_balance = 0.0, 0.0

    while True:
        data = fetch_kline_data(symbol)
        if data is None:
            time.sleep(30)
            continue

        data['MA_5'] = calculate_moving_average(data.iloc[::-1], 5)
        data['MA_20'] = calculate_moving_average(data.iloc[::-1], 20)
        data['MA_60'] = calculate_moving_average(data.iloc[::-1], 60)
        data['RSI'] = calculate_rsi(data)
        data['ATR'] = calculate_atr(data)

        latest = data.iloc[0]

        # 매수 신호
        if latest['MA_5'] > latest['MA_20'] > latest['MA_60'] and latest['RSI'] < 70:
            long_confirmation_count += 1
            print(f'long_confirmation_count:{long_confirmation_count}')
        else:
            long_confirmation_count = 0

        if long_confirmation_count > confirmation_threshold and not long_position_flag:
            long_entry_balance = get_available_balance()
            long_order_id, long_entry_price = execute_trade('buy', latest['close'])
            if long_order_id:
                long_position_flag = True
                cancel_unfilled_order_after_timeout(long_order_id)

        # 예상 수익률이 0.2% 도달 시 Stop Loss 수정
        if long_position_flag and long_order_id:
            expected_profit = (latest['close'] - long_entry_price) / long_entry_price * 100
            if expected_profit >= 0.2:
                new_stop_loss_price = latest['close'] * 0.999
                amend_stop_loss(long_order_id, new_stop_loss_price)

        # 롱 포지션 종료 확인 카운터
        if long_position_flag and (latest['MA_5'] < latest['MA_20'] or latest['RSI'] > 80):
            long_exit_confirmation_count += 1
            print(f'long_confirmation_count:{long_exit_confirmation_count}')
        else:
            long_exit_confirmation_count = 0

        # 롱 포지션 종료 확인
        if long_position_flag and long_exit_confirmation_count > confirmation_threshold:
            if long_order_id:
                cancel_order(long_order_id)
            long_position_flag = False
            long_order_id = None
            closing_balance = get_available_balance()
            profit = closing_balance - long_entry_balance
            notify(f"Long position closed. Profit: {profit:.2f} USDT")
            time.sleep(1200)  # 거래 완료 후 20분 대기

        # 롱 포지션 TP로 종료된 경우
        if long_position_flag and long_order_id:
            order_status = session.get_order_history(orderId=long_order_id)
            if order_status['result']['list'][0]['order_status'] == 'Filled':
                long_position_flag = False
                closing_balance = get_available_balance()
                profit = closing_balance - long_entry_balance
                notify(f"Long position closed via TP. Profit: {profit:.2f} USDT")
                time.sleep(1200)  # 거래 완료 후 20분 대기

        # 매도 신호
        if latest['MA_5'] < latest['MA_20'] < latest['MA_60'] and latest['RSI'] > 30:
            short_confirmation_count += 1
            print(f'short_confirmation_count:{short_confirmation_count}')
        else:
            short_confirmation_count = 0

        if short_confirmation_count > confirmation_threshold and not short_position_flag:
            short_entry_balance = get_available_balance()
            short_order_id, short_entry_price = execute_trade('sell', latest['close'])
            if short_order_id:
                short_position_flag = True
                cancel_unfilled_order_after_timeout(short_order_id)

        # 예상 수익률이 0.2% 도달 시 Stop Loss 수정
        if short_position_flag and short_order_id:
            expected_profit = (short_entry_price - latest['close']) / short_entry_price * 100
            if expected_profit >= 0.2:
                new_stop_loss_price = latest['close'] * 1.001
                amend_stop_loss(short_order_id, new_stop_loss_price)

        # 숏 포지션 종료 확인 카운터
        if short_position_flag and (latest['MA_5'] > latest['MA_20'] or latest['RSI'] < 20):
            short_exit_confirmation_count += 1
            print(f'short_confirmation_count:{short_exit_confirmation_count}')
        else:
            short_exit_confirmation_count = 0

        # 숏 포지션 종료 확인
        if short_position_flag and short_exit_confirmation_count > confirmation_threshold:
            if short_order_id:
                cancel_order(short_order_id)
                short_position_flag = False
                closing_balance = get_available_balance()
                profit = closing_balance - short_entry_balance
                notify(f"Short position closed. Profit: {profit:.2f} USDT")
                time.sleep(1200)  # 거래 완료 후 20분 대기

        # 숏 포지션 TP로 종료된 경우
        if short_position_flag and short_order_id:
            order_status = session.get_order_history(orderId=short_order_id)
            if order_status['result']['list'][0]['order_status'] == 'Filled':
                short_position_flag = False
                short_order_id = None
                closing_balance = get_available_balance()
                profit = closing_balance - short_entry_balance
                notify(f"Short position closed via TP. Profit: {profit:.2f} USDT")
                time.sleep(1200)  # 거래 완료 후 20분 대기

        time.sleep(10)

trading_strategy()
