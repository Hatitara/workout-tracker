import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import time
from streamlit_autorefresh import st_autorefresh
import streamlit.components.v1 as components

@st.cache_resource
def authorize_gspread():
    """
    Підключається до Google API, використовуючи Streamlit Secrets.
    ТІЛЬКИ повертає клієнт або повертає None. Жодних st.* елементів!
    """
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        print(f"Помилка авторизації gspread: {e}")
        return None

@st.cache_data(ttl=300)
def load_and_process_history(_all_sheets_data):
    """
    Processes all data from Google Sheets and converts it into a DataFrame suitable for analysis.
    """
    history_records = []
    workout_counter = 0

    for sheet_title, data in _all_sheets_data.items():
        if len(data) < 3:
            continue

        headers = data[1]
        exercise_rows = data[2:]

        workout_cols = {
            i: header for i, header in enumerate(headers)
            if "Workout" in header and "Actual" in header
        }

        if not workout_cols:
            continue

        for row_idx, row in enumerate(exercise_rows):
            exercise_name = row[0]
            if not exercise_name:
                continue

            for col_idx, day_title in workout_cols.items():
                actual_result = row[col_idx]
                if actual_result:
                    history_records.append({
                        "Sheet": sheet_title,
                        "Day": day_title,
                        "Exercise": exercise_name,
                        "Actual_Raw": actual_result,
                        "Workout_Order": workout_counter + int(day_title[8]),
                    })
        workout_counter += len(workout_cols)

    if not history_records:
        return pd.DataFrame()

    df = pd.DataFrame(history_records)

    def parse_actual(value_str):
        try:
            if 'sec' in value_str.lower():
                return int("".join(filter(str.isdigit, value_str.split('-')[0])))
            parts = [int(s.strip()) for s in value_str.replace(',', ' ').split() if s.isdigit()]
            return sum(parts)
        except Exception:
            return None

    df["Metric (Total Volume/Time)"] = df["Actual_Raw"].apply(parse_actual)
    df['Workout_Label'] = df['Sheet'].str.replace("Month 1 - ", "M1-") + " / " + df['Day'].str.replace(" (Actual)", "")
    df = df.sort_values(by="Workout_Order")

    return df

def calculate_overall_completion(all_sheets_data):
    """
    Calculates the overall completion percentage of all workouts.
    """
    total_slots = 0
    filled_slots = 0

    for sheet_title, data in all_sheets_data.items():
        if len(data) < 3:
            continue

        headers = data[1]
        exercise_rows = data[2:]

        workout_col_indices = [
            i for i, header in enumerate(headers)
            if "Workout" in header and "Actual" in header
        ]

        if not workout_col_indices:
            continue

        num_exercises_in_sheet = 0
        for row in exercise_rows:
            if row and row[0]:
                num_exercises_in_sheet += 1
            else:
                break

        if num_exercises_in_sheet == 0:
            continue

        total_slots += (num_exercises_in_sheet * len(workout_col_indices))

        for i in range(num_exercises_in_sheet):
            for col_idx in workout_col_indices:
                if exercise_rows[i][col_idx]:
                    filled_slots += 1

    if total_slots == 0:
        return 0, 0, 0.0

    percentage = (filled_slots / total_slots) * 100
    return total_slots, filled_slots, percentage

def render_history_tab():
    """
    Renders the 'Progress' tab. (Updated version with completion percentage)
    """
    st.title("📈 Твій Прогрес")

    if 'workbook' not in st.session_state:
        st.warning("Спочатку потрібно запустити програму з вкладки 'Тренування'.")
        return

    all_data = get_workout_data(st.session_state.client, st.secrets["gcp_service_account"]["sheet_id"])[1]

    st.subheader("Загальний Прогрес Виконання")
    total, filled, perc = calculate_overall_completion(all_data)

    if total > 0:
        st.progress(int(perc), text=f"{perc:.1f}% Завершено")
        col1, col2 = st.columns(2)
        col1.metric("Виконано вправ (всього)", f"{filled}")
        col2.metric("Загалом вправ у плані", f"{total}")
    else:
        st.info("Не знайдено вправ для розрахунку прогресу.")

    st.divider()

    df_history = load_and_process_history(all_data)

    if df_history.empty:
        st.info("Ти ще не завершив жодного тренування. Історія для графіків порожня.")
        return

    st.subheader("Аналіз по Вправах")
    all_exercises = df_history["Exercise"].unique()
    selected_exercise = st.selectbox(
        "Обери вправу, щоб побачити прогрес:",
        all_exercises
    )

    if selected_exercise:
        df_exercise = df_history[df_history["Exercise"] == selected_exercise].copy()

        if df_exercise.empty:
            st.warning("Немає даних для цієї вправи.")
            return

        st.subheader(f"Прогрес для: {selected_exercise}")

        chart_data = df_exercise[["Workout_Label", "Metric (Total Volume/Time)"]]
        chart_data = chart_data.set_index("Workout_Label")

        st.line_chart(chart_data)

        metric_type = "Загальний обсяг (повторення)"
        if 'sec' in df_exercise.iloc[0]["Actual_Raw"]:
             metric_type = "Загальний час (секунди)"

        st.caption(f"Графік показує '{metric_type}' по кожному тренувальному дню.")

        with st.expander("Показати таблицю з даними"):
            st.dataframe(df_exercise[[
                "Sheet", "Day", "Actual_Raw", "Metric (Total Volume/Time)"
            ]].set_index("Sheet"))

@st.cache_data(ttl=300)
def get_workout_data(_client, sheet_id):
    """
    Fetches all data from the spreadsheet in a single request.
    """
    try:
        workbook = _client.open_by_key(sheet_id)
        sheets = workbook.worksheets()

        all_sheets_data = {}
        for sheet in sheets:
            if sheet.title.startswith("Month"):
                all_sheets_data[sheet.title] = sheet.get_all_values()

        return workbook, all_sheets_data
    except Exception as e:
        st.error(f"Помилка читання таблиці: {e}")
        return None, None

def find_next_workout_and_exercises(all_sheets_data):
    """
    Finds the next workout day and assembles the list of exercises.
    """
    for sheet_title, data in all_sheets_data.items():
        if len(data) < 3:
            continue

        headers = data[1]
        exercise_rows = data[2:]

        workout_col_indices = [
            i for i, header in enumerate(headers)
            if "Workout" in header and "Actual" in header
        ]

        if not workout_col_indices:
            continue

        last_exercise_row_index = -1
        for i, row in enumerate(exercise_rows):
            if row and row[0]:
                last_exercise_row_index = i
            else:
                break

        if last_exercise_row_index == -1:
            continue

        for col_index in workout_col_indices:
            if not exercise_rows[last_exercise_row_index][col_index]:
                exercises_to_do = []
                for i, row in enumerate(exercise_rows):
                    if not row or not row[0]:
                        break

                    if not row[col_index]:
                        exercise = {
                            "name": row[0],
                            "sets_goal": row[1],
                            "reps_goal": row[2],
                            "rest": row[3],
                            "gspread_row": i + 3,
                            "gspread_col": col_index + 1
                        }
                        exercises_to_do.append(exercise)

                if exercises_to_do:
                    return sheet_title, exercises_to_do, headers[col_index]

    return None, [], None

def update_google_sheet(sheet_title, row, col, value):
    """
    Updates a single cell.
    """
    try:
        st.session_state.workbook.worksheet(sheet_title).update_cell(row, col, value)
        st.toast(f"Збережено: {value}", icon="✅")
    except Exception as e:
        st.error(f"Помилка збереження: {e}")

def initialize_session():
    """
    Runs once at the start of the session.
    Finds the next workout and stores it in the session state.
    """
    client = authorize_gspread()
    if client:
        st.toast("✅ Підключено до Google Sheets!", icon="🔌")
        st.session_state.client = client
        st.session_state.workbook, all_data = get_workout_data(
            client,
            st.secrets["gcp_service_account"]["sheet_id"]
        )

        if all_data:
            sheet_title, exercises, day_title = find_next_workout_and_exercises(all_data)
            st.session_state.sheet_title = sheet_title
            st.session_state.exercises_today = exercises
            st.session_state.day_title = day_title
            st.session_state.current_exercise_index = 0
            st.session_state.current_view = "workout"
            st.session_state.app_ready = True
        else:
            st.error("Не вдалося отримати дані з Google Sheet.")
            st.session_state.app_ready = False

    else:
        st.error("Помилка підключення до Google Sheets.")
        st.error("Перевір свої 'Secrets' в налаштуваннях Streamlit Cloud.")
        st.session_state.app_ready = False

def render_workout_view():
    """
    Renders the current exercise and input fields.
    """
    idx = st.session_state.current_exercise_index

    if idx >= len(st.session_state.exercises_today):
        st.session_state.current_view = "done"
        st.rerun()
        return

    ex = st.session_state.exercises_today[idx]

    st.header(f"🏋️ {ex['name']}")
    st.divider()

    col1, col2, col3 = st.columns(3)
    col1.metric("Підходи", ex['sets_goal'])
    col2.metric("Повторення", ex['reps_goal'])
    col3.metric("Відпочинок", ex['rest'])

    st.divider()

    with st.form(key=f"exercise_form_{idx}"):
        actual_result = st.text_input(
            "Ваш результат (напр. '10, 9, 8' або 'Done')",
            key=f"input_{idx}"
        )
        submitted = st.form_submit_button(
            "Зберегти та почати відпочинок",
            type="primary",
            use_container_width=True
        )

        if submitted:
            if not actual_result:
                st.warning("Будь ласка, введіть результат.")
                return

            update_google_sheet(
                st.session_state.sheet_title,
                ex['gspread_row'],
                ex['gspread_col'],
                actual_result
            )

            rest_time_str = ex['rest'].lower().replace('sec', '').strip()
            try:
                if '-' in rest_time_str:
                    rest_time_str = rest_time_str.split('-')[1]
                rest_duration = int(rest_time_str)
            except ValueError:
                st.warning("Не вдалося розпізнати час відпочинку. Ставлю 60 сек.")
                rest_duration = 5

            st.session_state.rest_duration = rest_duration
            st.session_state.rest_start_time = time.time()
            st.session_state.current_view = "rest"
            st.session_state.sound_played = False
            st.rerun()

def render_rest_view():
    """
    Renders the running rest timer and the next exercise. Updated version with one-time balloons and looping sound.
    """
    st_autorefresh(interval=1000, key="rest_timer_refresh")

    start_time = st.session_state.rest_start_time
    duration = st.session_state.rest_duration

    elapsed = time.time() - start_time
    remaining = int(duration - elapsed)

    if remaining > 0:
        st.header("⏳ Відпочинок...")

        minutes = remaining // 60
        seconds = remaining % 60
        st.metric("Залишилось часу:", f"{minutes:02d}:{seconds:02d}")

        next_idx = st.session_state.current_exercise_index + 1
        if next_idx < len(st.session_state.exercises_today):
            next_ex = st.session_state.exercises_today[next_idx]
            with st.expander(f"Наступна вправа: {next_ex['name']}", expanded=True):
                st.info("Підготуйся! Поки відпочиваєш, можеш загуглити техніку.")
                st.text(f"План: {next_ex['sets_goal']} / {next_ex['reps_goal']}")
        else:
            st.info("Це була остання вправа!")

    else:
        st.header("✅ Час вийшов!")

        if not st.session_state.get('timer_finished', False):
            st.balloons()
            st.session_state.timer_finished = True
            st.session_state.play_sound = True

        st.info("Натисніть 'Далі', щоб почати наступну вправу.")

        if st.session_state.get('play_sound', False):
            components.html(
                f"""
                <audio autoplay loop>
                    <source src="https://www.soundjay.com/buttons/beep-07a.mp3" type="audio/mpeg">
                </audio>
                """,
                height=0
            )

        if st.button("Далі!", type="primary", use_container_width=True):
            st.session_state.play_sound = False
            st.session_state.timer_finished = False

            st.session_state.current_exercise_index += 1
            st.session_state.current_view = "workout"
            st.rerun()

def render_done_view():
    """
    Renders the workout completion screen.
    """
    st.balloons()
    st.title("🎉 Чудова Робота! 🎉")
    st.header(f"Тренування '{st.session_state.day_title}' завершено.")
    st.subheader(f"Дані збережено в аркуші '{st.session_state.sheet_title}'.")

    if st.button("Почати нове тренування (якщо є)"):
        for key in st.session_state.keys():
            del st.session_state[key]
        st.rerun()

st.set_page_config(layout="centered")

tab1, tab2 = st.tabs(["Тренування 🏋️", "Прогрес 📈"])

with tab1:
    st.title("Мій Трекер Тренувань 🏋️")

    if 'app_ready' not in st.session_state:
        with st.spinner("Підключення до Google Sheets та пошук тренування..."):
            initialize_session()

    if st.session_state.get('app_ready', False):

        if not st.session_state.sheet_title or not st.session_state.exercises_today:
            st.success("🎉 Вітаємо! Всі тренування у всіх місяцях завершено!")
            st.image("https://media.tenor.com/1i1S2s-Yn-YAAAAC/the-office-stanley-hudson.gif")

        elif st.session_state.current_view == 'workout':
            render_workout_view()

        elif st.session_state.current_view == 'rest':
            render_rest_view()

        elif st.session_state.current_view == 'done':
            render_done_view()

    elif 'client' not in st.session_state:
        st.error("Не вдалося запустити програму. Перевір налаштування 'secrets.toml'.")

with tab2:
    if st.session_state.get('app_ready', False):
        render_history_tab()
    else:
        st.info("Перейди на вкладку 'Тренування', щоб завантажити дані.")
