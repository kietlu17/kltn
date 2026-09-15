const mongoose = require('mongoose');

const statsSchema = new mongoose.Schema(
  {
    peakViewers: { type: Number, default: 0 },
    totalViewers: { type: Number, default: 0 },
    totalMessages: { type: Number, default: 0 },
    productClicks: { type: Number, default: 0 },
    cartAdds: { type: Number, default: 0 }
  },
  { _id: false }
);

const liveSessionSchema = new mongoose.Schema(
  {
    shopId: { type: String, required: true, index: true },
    sellerId: { type: String, required: true, index: true },
    title: { type: String, required: true, trim: true, maxlength: 160 },
    description: { type: String, default: '', maxlength: 2000 },
    coverImage: { type: String, default: '' },
    status: {
      type: String,
      enum: ['scheduled', 'starting', 'live', 'paused', 'ending', 'ended', 'banned'],
      default: 'scheduled',
      index: true
    },
    provider: { type: String, default: 'livekit' },
    providerRoomId: { type: String, required: true, unique: true },
    playbackUrl: { type: String, default: '' },
    hlsPlaybackUrl: { type: String, default: '' },
    hlsPlaylistPath: { type: String, default: '' },
    egressId: { type: String, default: '' },
    egressStatus: { type: String, default: '' },
    visibility: {
      type: String,
      enum: ['public', 'followers_only', 'private'],
      default: 'public'
    },
    moderationStatus: {
      type: String,
      enum: ['normal', 'limited', 'banned'],
      default: 'normal'
    },
    activePinnedProductId: { type: String, default: null },
    scheduledAt: { type: Date, default: null },
    startedAt: { type: Date, default: null },
    endedAt: { type: Date, default: null },
    stats: { type: statsSchema, default: () => ({}) }
  },
  { timestamps: true }
);

liveSessionSchema.index({ shopId: 1, status: 1 });
liveSessionSchema.index({ createdAt: -1 });

module.exports = mongoose.model('LiveSession', liveSessionSchema);
