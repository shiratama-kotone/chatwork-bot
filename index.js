const axios = require('axios');

const apiKey = process.env.CHATWORK_API_KEY;
const roomId = process.env.CHATWORK_ROOM_ID;

async function sendMessage(message) {
    const url = `https://api.chatwork.com/v2/rooms/${roomId}/messages`;
    try {
        await axios.post(
            url,
            { body: message },
            {
                headers: {
                    'X-ChatWorkToken': apiKey,
                },
            }
        );
        console.log('Message sent:', message);
    } catch (error) {
        console.error('Error sending message:', error.response ? error.response.data : error.message);
    }
}

function getCurrentTimeMessage() {
    const now = new Date();
    const hours = now.getHours();
    return `${hours}時です！`;
}

function getDateChangeMessage() {
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth() + 1;
    const day = now.getDate();
    return `日付変更！今日は${year}年${month}月${day}日です！`;
}

// スケジュール設定
setInterval(() => {
    const now = new Date();
    const hours = now.getHours();
    const minutes = now.getMinutes();

    if (minutes === 0 && hours % 2 === 0) {
        sendMessage(getCurrentTimeMessage());
    }

    if (hours === 0 && minutes === 0) {
        sendMessage(getDateChangeMessage());
    }
}, 60 * 1000); // 毎分チェック
