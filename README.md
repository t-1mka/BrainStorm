# 🧠 Мозговой Штурм — Интерактивная Викторина

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Flask](https://img.shields.io/badge/Flask-3.0%2B-green)
![SocketIO](https://img.shields.io/badge/SocketIO-Realtime-orange)
![GigaChat](https://img.shields.io/badge/GigaChat-AI-purple)
![Render](https://img.shields.io/badge/Deployed-Render-46E3B7)

---

## 🌐 Играть онлайн

### 👇 Открыть с телефона — отсканируй QR-код:

<p align="center">
  <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://brainstorm-c0ap.onrender.com/" alt="QR-код сайта" width="200"/>
</p>

<p align="center">
  <a href="https://brainstorm-c0ap.onrender.com/">
    <strong>🔗 https://brainstorm-c0ap.onrender.com/</strong>
  </a>
</p>

> ⚠️ Бесплатный сервер на Render «засыпает» после 15 минут неактивности. Первый запуск может занять до 1 минуты — просто подожди.

---

## 🎮 Обзор

**Мозговой Штурм** — современная интерактивная викторина с искусственным интеллектом GigaChat. Создавай вопросы на любую тему и играй в реальном времени с нескольких устройств.

---

## ✨ Ключевые возможности

- 🤖 **GigaChat AI** — автоматическая генерация вопросов на любую тему с адаптацией под сложность
- 📱 **Мультиплатформенность** — игра с компьютера и телефона одновременно
- 🎯 **Три режима игры** — командный, все против всех, на время
- 🔄 **Fallback** — встроенный банк вопросов при недоступности AI
- ⚡ **Real-time** — WebSocket (SocketIO) для мгновенной синхронизации

---

## 🚀 Локальный запуск

### 1. Установка

```bash
git clone https://github.com/t-1mka/BrainStorm
cd BrainStorm
```

### 2. Конфигурация `.env`

```env
GIGACHAT_CREDENTIALS=ваш_ключ_авторизации
SECRET_KEY=ваш_секретный_ключ
```

### 3. Запуск

```bash
start.bat
```

### 4. Получение ключа GigaChat

1. Перейдите на [сайт разработчиков Сбер](https://developers.sber.ru/)
2. Войдите через Сбер ID
3. Создайте приложение и скопируйте ключ авторизации

---

## 🎮 Как играть

1. **Создай комнату** — введи имя, выбери количество вопросов, сложность и тему
2. **Присоединись** — другие игроки вводят код комнаты
3. **Играй** — выбирай правильные ответы, зарабатывай очки, следи за счётом

---

## 🔧 Технологический стек

| Слой | Технология |
|------|-----------|
| Backend | Python + Flask + Flask-SocketIO |
| Frontend | JavaScript + CSS |
| AI | GigaChat API (Сбербанк) |
| Real-time | WebSocket (SocketIO + eventlet) |
| Хостинг | Render |

---

## 🐛 Устранение проблем

**Не получается токен GigaChat** — проверь `GIGACHAT_CREDENTIALS` в `.env` и интернет-соединение

**Не запускается сервер** — убедись, что Python 3.10+ установлен, порт 5000 свободен

**Нет доступа с телефона** — убедись, что устройства в одной сети, используй IP из консоли
