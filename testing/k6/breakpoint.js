/**
 * Поиск ёмкости: линейный рост от 0 до MAX_RPS за время DURATION.
 *
 * Открытая модель (ramping-arrival-rate): частота растёт линейно,
 * k6 сам выделяет виртуальных пользователей для удержания частоты.
 * Кэш прогревается естественно по мере роста нагрузки.
 *
 * Запуск:
 *   k6 run --env MAX_RPS=800 --env DURATION=15m breakpoint.js
 *   k6 run --env MAX_RPS=50 --env DURATION=5m breakpoint.js  # итерация 0
 */

import http from 'k6/http';
import { SharedArray } from 'k6/data';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';
const MAX_RPS = parseInt(__ENV.MAX_RPS || '800');
const DURATION = __ENV.DURATION || '15m';
const N_REC = 12;
const N_SIMILAR = 6;

const params = new SharedArray('params', function () {
    return JSON.parse(open('../data/k6_params.json'));
});

const WEIGHT_REC = 0.10;
const WEIGHT_POP = 0.34;

export const options = {
    scenarios: {
        breakpoint: {
            executor: 'ramping-arrival-rate',
            startRate: 1,
            timeUnit: '1s',
            preAllocatedVUs: Math.max(MAX_RPS * 2, 100),
            maxVUs: MAX_RPS * 10,
            stages: [
                { target: MAX_RPS, duration: DURATION },
            ],
        },
    },
};

export default function () {
    const idx = Math.floor(Math.random() * params.length);
    const p = params[idx];
    const roll = Math.random();

    let url, name;

    if (roll < WEIGHT_REC) {
        url = `${BASE_URL}/recommendations/${p.u}?n=${N_REC}`;
        name = '/recommendations/{user_id}';
    } else if (roll < WEIGHT_POP) {
        url = `${BASE_URL}/recommendations/${p.u}/popular?n=${N_REC}`;
        name = '/recommendations/{user_id}/popular';
    } else {
        url = `${BASE_URL}/similar/${p.m}?n=${N_SIMILAR}`;
        name = '/similar/{movie_id}';
    }

    const res = http.get(url, { tags: { name: name } });

    check(res, {
        'код 200 или 404': (r) => r.status === 200 || r.status === 404,
    });
}
