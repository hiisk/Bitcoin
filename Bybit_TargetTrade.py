import tkinter as tk
from pybit.unified_trading import HTTP 
import time
import math
import threading
import datetime

session = HTTP(
    testnet=False,
    api_key="", #API KEY입력
    api_secret="", #API SECRET 입력
)

# 심볼 설정 (예: BTCUSDT)
symbol = 'BTCUSDT'

# 시간과 함께 텍스트 삽입 함수 정의
def insert_with_time(text_widget, text):
    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    text_widget.insert(tk.END, f"[{current_time}] {text}\n")

# 잔고 조회 예시
def get_wallet_balance(output_text):
    try:
        response = session.get_wallet_balance(accountType="Unified")  # 선물 계정 잔고 조회
        for i in response['result']['list'][0]['coin']:
            if i['coin'] == 'USDT':
                usdt_balance = float(i['walletBalance'])
                insert_with_time(output_text, f"사용 가능한 잔고: {round(usdt_balance,4)} USDT")
                return usdt_balance
    except Exception as e:
        insert_with_time(output_text, f"잔고 조회 중 오류 발생: {e}")
        return None
    

# 현재 가격 가져오기
def get_latest_price(output_text):
    try:
        ticker = session.get_tickers(category="linear", symbol=symbol)
        latest_price = float(ticker['result']['list'][0]['lastPrice'])
        return latest_price
    except Exception as e:
        insert_with_time(output_text, f"현재 가격 가져오기 중 오류 발생: {e}")
        return None

# 이익 실현 지정가 주문 함수 (Take Profit Limit)
def place_take_profit_limit(side, qty, take_profit_price, output_text):
    try:
        take_profit_order = session.place_order(
            category="linear",
            symbol=symbol,
            side="Sell" if side == "Buy" else "Buy",  # 매수 후 이익 실현은 "Sell", 매도 후 이익 실현은 "Buy"
            orderType="Limit",  # 이익 실현 지정가 주문
            qty=qty,
            price=take_profit_price  # 지정가 매도 가격
        )
        insert_with_time(output_text, f"이익 실현 지정가 주문 완료")
        return True
    except Exception as e:
        insert_with_time(output_text, f"이익 실현 지정가 주문 설정 중 오류 발생: {e}")

# 지정가 주문 및 손절 설정 함수 (Stop Loss 포함)
def place_order_with_sl(side, qty, price, stop_loss_price, output_text):
    try:           
        order = session.place_order(
            category="linear",
            symbol=symbol,
            side=side,  # "Buy" 또는 "Sell"
            orderType="Limit",  # 지정가 주문
            qty=qty,  # 주문 수량
            price=price,  # 주문 가격
            isLeverage=1,
            stopLoss=stop_loss_price,
        )

        insert_with_time(output_text, f"{side} 지정가 주문 완료")
        return order
    except Exception as e:
        insert_with_time(output_text, f"{side} 주문 중 오류 발생: {e}")
        return None

# 주문 상태를 주기적으로 확인하는 함수
def monitor_order(total_qty, output_text):

    pre_leavesQty = 0 # 이전에 체결된 양을 확인하려 만든 변수
    while True:
        order_info = session.get_order_history(category="linear", symbol=symbol, limit=2)
        status = order_info["result"]["list"][0]["orderStatus"]
        leavesQty = float(order_info["result"]["list"][0]["leavesQty"])

        if status:
            if status in ["Untriggered"] and leavesQty == total_qty:  # 주문이 완료되거나 취소된 경우 루프 종료
                insert_with_time(output_text, f"주문 완료 확인")
                return True
            elif status in ["Cancelled", "Rejected"]:
                insert_with_time(output_text, f"주문 취소 확인")
                return False
        
        if pre_leavesQty != leavesQty and (status not in ["Cancelled", "Rejected"]):
            pre_leavesQty = leavesQty
            insert_with_time(output_text, f"주문 체결 대기중 Qty: {total_qty-leavesQty}/{total_qty}")
            output_text.see(tk.END)  # 스크롤을 마지막으로 이동
        time.sleep(1)  # 1초 대기 후 다시 확인

def leverage_changed(leverage, output_text):
    session.set_leverage(
        category="linear",
        symbol=symbol,
        buyLeverage=str(leverage),
        sellLeverage=str(leverage)
    )
    insert_with_time(output_text, f"레버리지가 {leverage}로 변경되었습니다.")

def cancel_all_order(output_text):
    session.cancel_all_orders(
        category="linear",
        settleCoin="USDT",
    )
    insert_with_time(output_text, "매매가 전부 취소되었습니다.")

# 자동 매매 로직
def auto_trade(side, input_limit, leverage, maker_fee, taker_fee, profit_percent, stop_loss_percent, output_text):
    output_text.see(tk.END)  # 스크롤을 마지막으로 이동

    # 이익, 손절 가격 계산
    take_profit_price = round(input_limit * (1 + profit_percent/100/leverage) if side == "Buy" else input_limit * (1 - profit_percent/100/leverage),1)
    stop_loss_price = round(input_limit * (1 - stop_loss_percent/100/leverage) if side == "Buy" else input_limit * (1 + stop_loss_percent/100/leverage),1)

    if side == "Buy":

        balance = (get_wallet_balance(output_text)/(1 + taker_fee*0.25 + maker_fee*0.75)) * leverage  # 레버리지 적용 후 잔고 / Taker수수료로 변경 Maker 수수료 반영
        total_qty = math.floor(balance / input_limit * 1000) / 1000  # 최소 단위 0.001로 맞추기

        # 지정가 주문 설정
        place_order_with_sl(side, total_qty, input_limit, stop_loss_price, output_text)

        # 목표 이익 가격 및 손절 가격 직접 계산하여 출력
        insert_with_time(output_text, f"목표 이익 가격 (지정가): {take_profit_price} USDT")
        insert_with_time(output_text, f"손절 가격 (시장가): {stop_loss_price} USDT")

        time.sleep(5)  # 5초대기
        
        # 이익 실현 주문 설정
        if monitor_order(total_qty, output_text):  # 지정가 주문이 성공적으로 완료되었을 때
            time.sleep(1)  # 1초대기
            place_take_profit_limit(side, total_qty, take_profit_price, output_text)
            return True
        
    else:  # "Sell"

        balance = (get_wallet_balance(output_text)/(1 + taker_fee*0.25 + maker_fee*0.75)) * leverage  # 레버리지 적용 후 잔고 / Taker수수료로 변경 Maker 수수료 반영
        total_qty = math.floor(balance / input_limit * 1000) / 1000  # 최소 단위 0.001로 맞추기

        # 지정가 주문 설정
        place_order_with_sl(side, total_qty, input_limit, stop_loss_price, output_text)

        # 목표 이익 가격 및 손절 가격 직접 계산하여 출력
        insert_with_time(output_text, f"목표 이익 가격 (지정가): {take_profit_price:.6f} USDT")
        insert_with_time(output_text, f"손절 가격 (시장가): {stop_loss_price:.6f} USDT")

        time.sleep(5)  # 5초대기

        # 이익 실현 주문 설정
        if monitor_order(total_qty, output_text):  # 지정가 주문이 성공적으로 완료되었을 때
            time.sleep(1)  # 1초대기
            place_take_profit_limit(side, total_qty, take_profit_price, output_text)
            return True
        
# GUI 설정
def start_gui():
    root = tk.Tk()
    root.title("Bybit 자동 매매")
    root.geometry("600x600")
    root.configure(bg="#2E2E2E")

    # Frame for Inputs
    input_frame = tk.Frame(root, bg="#2E2E2E")
    input_frame.pack(pady=10)

    # 매수값 입력
    input_label = tk.Label(input_frame, text="매수값:", bg="#2E2E2E", fg="white")
    input_label.grid(row=0, column=0, sticky="e")
    input_entry = tk.Entry(input_frame)
    input_entry.grid(row=0, column=1, padx=5)

    # 레버리지 입력
    leverage_label = tk.Label(input_frame, text="레버리지:", bg="#2E2E2E", fg="white")
    leverage_label.grid(row=1, column=0, sticky="e")
    leverage_entry = tk.Entry(input_frame)
    leverage_entry.grid(row=1, column=1, padx=5)
    leverage_entry.insert(0, 5)

    # Maker 및 Taker 수수료 입력
    maker_fee_label = tk.Label(input_frame, text="Maker 수수료 (%):", bg="#2E2E2E", fg="white")
    maker_fee_label.grid(row=2, column=0, sticky="e")
    maker_fee_entry = tk.Entry(input_frame)
    maker_fee_entry.grid(row=2, column=1, padx=5)
    maker_fee_entry.insert(0, 0.014)

    taker_fee_label = tk.Label(input_frame, text="Taker 수수료 (%):", bg="#2E2E2E", fg="white")
    taker_fee_label.grid(row=3, column=0, sticky="e")
    taker_fee_entry = tk.Entry(input_frame)
    taker_fee_entry.grid(row=3, column=1, padx=5)
    taker_fee_entry.insert(0, 0.035)

    # 목표 이익 및 손절 비율 입력
    profit_percent_label = tk.Label(input_frame, text="목표 이익 비율 (%):", bg="#2E2E2E", fg="white")
    profit_percent_label.grid(row=4, column=0, sticky="e")
    profit_percent_entry = tk.Entry(input_frame)
    profit_percent_entry.grid(row=4, column=1, padx=5)
    profit_percent_entry.insert(0, 3)

    stop_loss_percent_label = tk.Label(input_frame, text="손절 비율 (%):", bg="#2E2E2E", fg="white")
    stop_loss_percent_label.grid(row=5, column=0, sticky="e")
    stop_loss_percent_entry = tk.Entry(input_frame)
    stop_loss_percent_entry.grid(row=5, column=1, padx=5)
    stop_loss_percent_entry.insert(0, 2)

    # 출력 텍스트 상자
    output_text = tk.Text(root, height=20, width=70)
    output_text.pack(pady=10)
    
    # 매수 및 매도 버튼을 옆으로 배치
    button_frame = tk.Frame(root, bg="#2E2E2E")
    button_frame.pack(pady=10)

    def run_auto_trade(side):
        threading.Thread(target=auto_trade, args=(side, float(input_entry.get()), int(leverage_entry.get()), float(maker_fee_entry.get()), float(taker_fee_entry.get()), float(profit_percent_entry.get()), float(stop_loss_percent_entry.get()), output_text)).start()

    buy_button = tk.Button(button_frame, text="Long", command=lambda: run_auto_trade("Buy"), width=30, height=3, bg="#C8E6C9", fg="black")
    buy_button.grid(row=0, column=0, padx=5)

    sell_button = tk.Button(button_frame, text="Short", command=lambda: run_auto_trade("Sell"), width=30, height=3, bg="#FFCCBC", fg="black")
    sell_button.grid(row=0, column=1, padx=5)

    # 매수 및 매도 버튼을 옆으로 배치
    button_frame_2 = tk.Frame(root, bg="#2E2E2E")
    button_frame_2.pack(pady=10)

    # 로그 비우기 버튼
    clear_log_button = tk.Button(button_frame_2, text="로그 비우기", command=lambda: output_text.delete(1.0, tk.END), bg="#FFF9C4", fg="black", width=15)
    clear_log_button.grid(row=0, column=0, padx=5)

    # 레버리지 변경 버튼
    leverage_button = tk.Button(button_frame_2, text="레버리지 변경", command=lambda: leverage_changed(int(leverage_entry.get()),output_text), bg="#D1C4E9", fg="black", width=15)
    leverage_button.grid(row=0, column=1, padx=5)

    # 취소 버튼
    cancel_button = tk.Button(button_frame_2, text="취소", command=lambda: cancel_all_order(output_text), bg="#FFAB91", fg="black", width=15)
    cancel_button.grid(row=0, column=2, padx=5)

    # GUI 실행
    root.mainloop()

start_gui()