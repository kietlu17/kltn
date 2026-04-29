const mongoose = require('mongoose');

async function connectMongo() {
  const uri = process.env.MONGO_URI || 'mongodb://localhost:27017/auth-service';
  mongoose.set('strictQuery', true);
  await mongoose.connect(uri);
  console.log('Auth Service connected to MongoDB');
}

module.exports = { connectMongo };
