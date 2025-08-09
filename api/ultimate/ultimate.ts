import type { VercelRequest, VercelResponse } from '@vercel/node';
import { DateTime } from 'luxon';

// services na RAIZ (3 níveis acima) + extensão .ts
import { getNowBRT } from '../../../services/timeService.ts';
import { runUltimateAnalysis } from '../../../services/geminiService.ts';

type UltimateResponse = {
  schema_version: string;
  request_id: string;
  generated_at: string;
  horizon: '24h';
  ultimate: boolean;
  signals: any[];
};

const reqId = () => Math.random().toString(36).slice(2);

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const request_id = req.headers['x-request-id']?.toString() || reqId();
  const startedAt = Date.now();

  const enabled = process.env.LUCRA_ULTIMATE === 'true' || req.query.ultimate === '1';
  if (!enabled) {
    return res.status(403).json({ schema_version: '2.0.0', request_id, error: 'ultimate_disabled' });
  }

  try {
    const watchlist =
      (typeof req.query.watchlist === 'string'
        ? (req.query.watchlist as string).split(',').map(s => s.trim()).filter(Boolean)
        : null) || ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'];

    const now = getNowBRT();
    const horizonHours = Number((req.query.h as string) || '24');

    const analysis = await runUltimateAnalysis({
      watchlist,
      nowISO: now.toISO(),
      horizonHours,
      requireMinScore: 8.5,
      requireProb: 0.9
    });

    const payload: UltimateResponse = {
      schema_version: '2.0.0',
      request_id,
      generated_at: DateTime.now().toISO(),
      horizon: '24h',
      ultimate: true,
      signals: analysis?.signals || []
    };

    res.setHeader('Cache-Control', 'no-store');
    return res.status(200).json(payload);
  } catch (err: any) {
    return res.status(500).json({
      schema_version: '2.0.0',
      request_id,
      error: err?.message || 'internal_error'
    });
  } finally {
    res.setHeader('x-runtime-ms', String(Date.now() - startedAt));
  }
}

// Execução local (opcional)
if (require.main === module) {
  const express = require('express');
  const app = express();
  app.get('/api/ultimate', (req: any, res: any) => handler(req, res));
  const port = process.env.PORT || 3001;
  app.listen(port, () =>
    console.log(`Lucra Ultimate local: http://localhost:${port}/api/ultimate`)
  );
}
