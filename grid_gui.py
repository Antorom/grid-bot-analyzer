import streamlit as st
import ccxt
import pandas as pd
import time

st.set_page_config(page_title="Grid Bot Backtester", layout="wide")
st.title("🤖 Анализатор и Оптимизатор сеточного бота")

st.sidebar.header("Настройки симуляции")

# Поле для ручного ввода монеты
symbol_input = st.sidebar.text_input("Торговая пара", value="LIT/USDT")
base_symbol = symbol_input.upper().strip()

# Переключатель типа рынка
market_type = st.sidebar.radio("Тип рынка", ["Спот (Spot)", "Фьючерсы (Futures)"])
days_to_fetch = st.sidebar.slider("Период истории (дней)", 7, 180, 90)

st.sidebar.subheader("Стратегия")
bot_direction = st.sidebar.radio("Направление бота", ["Лонг (Long)", "Шорт (Short)"])

st.sidebar.subheader("Диапазон сетки")
price_lower = st.sidebar.number_input("Нижняя граница", value=0.8000, format="%.4f")
price_upper = st.sidebar.number_input("Верхняя граница", value=4.0000, format="%.4f")

grid_mode = st.sidebar.radio("Режим работы", [
    "Одиночный тест (кол-во сеток)", 
    "Одиночный тест (шаг в $)",
    "Авто-подбор шага (Оптимизатор) 🤖"
])

# Переменные для одиночного теста
grids_count = 0
actual_step = 0

# Переменные для оптимизатора
min_step, max_step, step_interval, min_trades = 0, 0, 0, 0

if grid_mode == "Одиночный тест (кол-во сеток)":
    grids_count = st.sidebar.number_input("Количество сеток", min_value=2, max_value=1000, value=30)
    actual_step = (price_upper - price_lower) / grids_count
elif grid_mode == "Одиночный тест (шаг в $)":
    step_input = st.sidebar.number_input("Шаг сетки ($)", min_value=0.0001, value=0.0200, format="%.4f")
    grids_count = int(round((price_upper - price_lower) / step_input))
    actual_step = (price_upper - price_lower) / grids_count if grids_count > 0 else step_input
    st.sidebar.info(f"Рассчитано сеток: **{grids_count}**")
else:
    st.sidebar.info("Укажи диапазон поиска. Бот переберет варианты и найдет самый прибыльный.")
    min_step = st.sidebar.number_input("От (мин. шаг $)", value=0.0100, format="%.4f")
    max_step = st.sidebar.number_input("До (макс. шаг $)", value=0.2000, format="%.4f")
    step_interval = st.sidebar.number_input("Прибавлять по ($)", value=0.0100, format="%.4f")
    min_trades = st.sidebar.number_input("Мин. сделок в день", value=2.0, format="%.1f")

st.sidebar.subheader("Капитал")
investment = st.sidebar.number_input("Депозит (USDT)", value=100.0, step=10.0)
leverage = st.sidebar.slider("Плечо", 1, 20, 3)
fee_rate = 0.0002 
total_volume = investment * leverage 

def run_simulation_core(step_to_test, df_data):
    g_count = int(round((price_upper - price_lower) / step_to_test))
    if g_count < 2: return None
    a_step = (price_upper - price_lower) / g_count
    o_usdt = total_volume / g_count 
    
    grid_levels = [price_lower + i * a_step for i in range(g_count + 1)]
    grid_state = {level: False for level in grid_levels} 

    total_profit = 0.0
    total_commission = 0.0
    t_count = 0
    last_price = df_data.iloc[0]['open']

    # Инициализация стартовых позиций бота
    for level in grid_levels:
        if bot_direction == "Лонг (Long)":
            if level < last_price:
                grid_state[level] = True
        else:
            if level + a_step > last_price:
                grid_state[level] = True

    for index, row in df_data.iterrows():
        high = row['high']
        low = row['low']
        
        for level in grid_levels:
            if bot_direction == "Лонг (Long)":
                if low <= level and not grid_state[level]:
                    grid_state[level] = True
                elif high >= level + a_step and grid_state[level]:
                    grid_state[level] = False
                    
                    coins_bought = o_usdt / level
                    buy_fee = o_usdt * fee_rate
                    sell_value = coins_bought * (level + a_step)
                    sell_fee = sell_value * fee_rate
                    
                    cycle_commission = buy_fee + sell_fee
                    total_commission += cycle_commission
                    
                    profit = (sell_value - sell_fee) - (o_usdt + buy_fee)
                    if profit > 0:
                        total_profit += profit
                        t_count += 1
            else:
                if high >= level + a_step and not grid_state[level]:
                    grid_state[level] = True
                elif low <= level and grid_state[level]:
                    grid_state[level] = False
                    
                    coins_shorted = o_usdt / (level + a_step)
                    short_value = o_usdt
                    sell_fee = short_value * fee_rate
                    
                    buy_value = coins_shorted * level
                    buy_fee = buy_value * fee_rate
                    
                    cycle_commission = sell_fee + buy_fee
                    total_commission += cycle_commission
                    
                    profit = (short_value - sell_fee) - (buy_value + buy_fee)
                    if profit > 0:
                        total_profit += profit
                        t_count += 1

    return {
        'Шаг ($)': round(a_step, 4),
        'Сеток': g_count,
        'Ордер ($)': round(o_usdt, 2),
        'Сделок всего': t_count,
        'Сделок в день': round(t_count / days_to_fetch, 1),
        'Комиссия ($)': round(total_commission, 2),
        'Чистая прибыль ($)': round(total_profit, 2)
    }

if st.sidebar.button("🚀 Запустить симуляцию", type="primary"):
    
    # Автоматически подстраиваем тикер под фьючерсы, если нужно
    if market_type == "Фьючерсы (Futures)" and ":" not in base_symbol:
        symbol = f"{base_symbol}:USDT"
    else:
        symbol = base_symbol

    with st.spinner(f'Загрузка свечей {symbol} с Pionex за {days_to_fetch} дней...'):
        
        # Настраиваем биржу
        exchange_config = {'enableRateLimit': True}
        if market_type == "Фьючерсы (Futures)":
            exchange_config['options'] = {'defaultType': 'swap'}
            
        exchange = ccxt.pionex(exchange_config)
        
        since = exchange.milliseconds() - (days_to_fetch * 24 * 60 * 60 * 1000)
        all_ohlcv = []
        
        while since < exchange.milliseconds():
            try:
                data = exchange.fetch_ohlcv(symbol, '1m', since, 1000)
                if not data: break
                since = data[-1][0] + 60000 
                all_ohlcv.extend(data)
                time.sleep(0.05)
            except Exception as e:
                st.error(f"Ошибка загрузки: {e}")
                break

        if all_ohlcv:
            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df.drop_duplicates(subset='timestamp', inplace=True)
            st.success(f"✅ Данные загружены! Обработано {len(df)} свечей.")
            st.markdown("---")

            if grid_mode != "Авто-подбор шага (Оптимизатор) 🤖":
                if grids_count < 2:
                    st.error("Ошибка: Слишком крупный шаг для этого диапазона.")
                else:
                    with st.spinner('Считаем...'):
                        res = run_simulation_core(actual_step, df)
                    
                    st.header(f"📊 Результат для {symbol} ({bot_direction})")
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Чистая прибыль", f"+${res['Чистая прибыль ($)']:.2f}", f"{res['Чистая прибыль ($)']/investment*100:.2f}%")
                    col2.metric("Всего сделок", f"{res['Сделок всего']}", f"{res['Сделок в день']} в день")
                    col3.metric("Прибыль с 1 сетки", f"${res['Чистая прибыль ($)']/res['Сделок всего'] if res['Сделок всего'] > 0 else 0:.4f}")
                    col4.metric("Уплачено комиссии", f"${res['Комиссия ($)']:.2f}")

            else:
                unique_grids = set()
                curr = min_step
                while curr <= max_step + (step_interval * 0.1): 
                    if curr > 0:
                        g_count = int(round((price_upper - price_lower) / curr))
                        if g_count >= 2:
                            unique_grids.add(g_count)
                    curr += step_interval

                steps_to_test = [(price_upper - price_lower) / g for g in sorted(list(unique_grids), reverse=True)]

                results = []
                progress_text = f"Анализируем стратегии (уникальных вариантов: {len(steps_to_test)})..."
                my_bar = st.progress(0, text=progress_text)

                for i, s in enumerate(steps_to_test):
                    res = run_simulation_core(s, df)
                    if res:
                        results.append(res)
                    my_bar.progress((i + 1) / len(steps_to_test), text=progress_text)
                
                my_bar.empty()

                if results:
                    active_results = [r for r in results if r['Сделок в день'] >= min_trades]
                    if not active_results:
                        st.warning(f"Нет вариантов, делающих {min_trades} сделок в день. Показываю лучшие из тех, что есть.")
                        active_results = results

                    best_res = max(active_results, key=lambda x: x['Чистая прибыль ($)'])
                    
                    st.header(f"🏆 Идеальная конфигурация найдена ({bot_direction})")
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Лучший шаг", f"${best_res['Шаг ($)']:.4f}")
                    col2.metric("Сеток", f"{best_res['Сеток']}")
                    col3.metric("Чистая прибыль", f"+${best_res['Чистая прибыль ($)']:.2f}", f"{best_res['Чистая прибыль ($)']/investment*100:.2f}%")
                    col4.metric("Сделок в день", f"{best_res['Сделок в день']}")
                    
                    st.subheader("Сравнительная таблица протестированных вариантов")
                    res_df = pd.DataFrame(results)
                    res_df = res_df.sort_values(by='Чистая прибыль ($)', ascending=False).reset_index(drop=True)
                    
                    st.dataframe(
                        res_df.style.highlight_max(subset=['Чистая прибыль ($)'], color='lightgreen'), 
                        use_container_width=True
                    )
        else:
            st.warning("Не удалось загрузить данные по этой монете. Проверь правильность написания тикера.")