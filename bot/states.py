from aiogram.fsm.state import State, StatesGroup


class SettingsState(StatesGroup):
    waiting_lolz_token = State()
    waiting_lolz_secret = State()
    waiting_funpay_key = State()
    waiting_markup = State()
    waiting_proxy = State()
    # Price drop settings
    waiting_price_drop_days = State()
    waiting_price_drop_percent = State()
    waiting_price_drop_floor = State()
    # Balance alert
    waiting_balance_alert = State()


class DeleteLotState(StatesGroup):
    waiting_lot_choice = State()


class LotState(StatesGroup):
    waiting_account_tag = State()  # when tag couldn't be extracted automatically
