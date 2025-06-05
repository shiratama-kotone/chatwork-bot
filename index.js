const express = require('express');
const axios = require('axios');
const app = express();

app.use(express.json());

const apiKey = process.env.CHATWORK_API_KEY;
const roomId = process.env.CHATWORK_ROOM_ID; // 返信用のルームID

app.get('/', (req, res) => {
  res.send('Bot is running!');
});

// Webhook受け取り用エンドポイント
app.post('/webhook', async (req, res) => {
  const event = req.body;

  // ログでWebhookの中身確認
  console.log('Webhook payload:', JSON.stringify(event, null, 2));

  // ChatworkのWebhookがメッセージ作成イベントか確認
  if (event.webhook_event === 'message_created') {
    const message = event.body.message || '';
    const fromAccountId = event.body.from_account.account_id;
    const groupName = event.body.room.name;

    if (message.trim() === '/test') {
      const replyMessage =
        `[info][title]テストメッセージ[/title]\n` +
        `[piconname:${fromAccountId}]さんが、グループ${groupName}でテストを要求しました。[/info]`;

      try {
        await axios.post(
          `https://api.chatwork.com/v2/rooms/${roomId}/messages`,
          { body: replyMessage },
          { headers: { 'X-ChatWorkToken': apiKey } }
        );
        console.log('Test message sent');
      } catch (e) {
        console.error('Error sending test message:', e.response?.data || e.message);
      }
    }
  }

  res.status(200).send('OK');
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});
