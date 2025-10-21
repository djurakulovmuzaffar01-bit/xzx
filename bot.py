from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import asyncio

TOKEN = "BOT_TOKENINGNI_BU_YERGA_QO'Y"  # @BotFather bergan tokenni bu yerga yoz
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🌐 Open Mini App",
                web_app=WebAppInfo(url="https://djurakulovmuzaffar01-bit.github.io/xzx/")  # GitHub Pages manziling
            )]
        ]
    )
    await message.answer("Salom jigar! Mini Appni och 👇", reply_markup=keyboard)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
