import type { VercelRequest, VercelResponse } from '@vercel/node';
import { DateTime } from 'luxon';

// services na RAIZ (3 níveis acima) + extensão .ts
import { fetchLivePrices } from '../../../services/marketService.ts';
import { getNowBRT } from '../../../services/timeService.ts';

type CoreSignal = {
  symbol: string;
  side: 'BUY' | 'SELL';
  entry: number;
  target: number;
  stop_loss: number;
  entrada_datahora: string;
  saida_datahora: string;
};

type CoreResponse = {
  schema_version: string;
  request_id: string;
  generated_at: string;
  horizon: '24h';
  signals: CoreSignal[];
};

const reqId = () => Math.random().toString(36).slice(2);
const withTZ = (dt: DateTime) => dt.setZone('America/Sao_Paulo');

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const request_id = req.headers['x-request-id']?.toString() || reqId();
  const startedAt = Date.now();

  try {
    const watchlist =
      (typeof req.query.watchlist === 'string'
        ? (req.query.watchlist as string).split(',').map(s => s.trim()).filter(Boolean)
        : null) || ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'];

    const now = getNowBRT();
    const entrada = withTZ(now);
    const saida = withTZ(now.plus({ hours: 24 }));

    const prices = await fetchLivePrices(watchlist);

    const signals: CoreSignal[] = watchlist.map((symbol) => {
      const px = prices?.[symbol]?.price ?? null;
      const entry = px ?? 0;
      return {
        symbol,
        side: 'BUY',
        entry,
        target: px ? Number((px * 1.02).toFixed(6)) : 0,
        stop_loss: px ? Number((px * 0.98).toFixed(6)) : 0,
        entrada_datahora: entrada.toFormat('yyyy-LL-dd HH:mm:ss'),
        saida_datahora: saida.toFormat('yyyy-LL-dd HH:mm:ss'),
      };
    });

    const payload: CoreResponse = {
      schema_version: '1.0.0',
      request_id,
      generated_at: withTZ(DateTime.now()).toISO(),
      horizon: '24h',
      signals
    };

    res.setHeader('Cache-Control', 'no-store');
    return res.status(200).json(payload);
  } catch (err: any) {
    return res.status(500).json({
      schema_version: '1.0.0',
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
  app.get('/api/analise', (req: any, res: any) => handler(req, res));
  const port = process.env.PORT || 3000;
  app.listen(port, () =>
    console.log(`Lucra Core local: http://localhost:${port}/api/analise`)
  );
}
