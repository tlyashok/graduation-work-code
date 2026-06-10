/**
 * Нагрузочный скрипт k6 для рекомендательного сервиса.
 *
 * Открытая модель (constant-arrival-rate): подаёт запросы с фиксированной частотой
 * независимо от времени отклика сервера.
 *
 * Веса эндпоинтов по ручным сессиям (§3.1):
 *   GET /recommendations/{user_id}         - 10%
 *   GET /recommendations/{user_id}/popular - 24%
 *   GET /similar/{movie_id}                - 66%
 *
 * Параметры (user_id, movie_id) заранее заготовлены из ratings.csv набора
 * MovieLens 25M скриптом generate_params.py с сохранением распределения активности.
 *
 * Запуск:
 *   k6 run --env RPS=100 --env DURATION=60s loadtest.js
 *   k6 run --env RPS=200 --env DURATION=60s --env BASE_URL=http://localhost:8000 loadtest.js
 */

import http from 'k6/http';
import { SharedArray } from 'k6/data';
import { check } from 'k6';

// --- Параметры ---
const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';
const RPS = parseInt(__ENV.RPS || '100');
const DURATION = __ENV.DURATION || '60s';
const N_REC = 12;
const N_SIMILAR = 6;

// --- Загрузка заранее подготовленных параметров ---
const params = new SharedArray('params', function () {
    return JSON.parse(open('../data/k6_params.json'));
});

// --- Веса эндпоинтов (накопленная вероятность) ---
// 10% персональные, 24% по популярности, 66% похожие
const WEIGHT_REC = 0.10;
const WEIGHT_POP = 0.34;  // 0.10 + 0.24
// остаток (0.34..1.0) = похожие

// --- Параметры k6: постоянная частота запросов (открытая модель) ---
export const options = {
    scenarios: {
        open_model: {
            executor: 'constant-arrival-rate',
            rate: RPS,
            timeUnit: '1s',
            duration: DURATION,
            // Небольшой пул VU с keep-alive: при задержке в единицы мс одновременных
            // запросов мало (rps*latency), а большой пул открывал бы тысячи соединений
            // -> сервис упирался бы в лимит дескрипторов и логировал ошибки accept,
            // что забивало профиль. Используется для профилировочной нагрузки (profile.py).
            preAllocatedVUs: 20,
            maxVUs: 100,
        },
    },
};

export default function () {
    const idx = Math.floor(Math.random() * params.length);
    const p = params[idx];
    const roll = Math.random();

    let url, name;

    if (roll < WEIGHT_REC) {
        // Персональные рекомендации (10%)
        url = `${BASE_URL}/recommendations/${p.u}?n=${N_REC}`;
        name = '/recommendations/{user_id}';
    } else if (roll < WEIGHT_POP) {
        // Рекомендации по популярности (24%)
        url = `${BASE_URL}/recommendations/${p.u}/popular?n=${N_REC}`;
        name = '/recommendations/{user_id}/popular';
    } else {
        // Похожие фильмы (66%)
        url = `${BASE_URL}/similar/${p.m}?n=${N_SIMILAR}`;
        name = '/similar/{movie_id}';
    }

    const res = http.get(url, { tags: { name: name } });

    check(res, {
        'код 200 или 404': (r) => r.status === 200 || r.status === 404,
    });
}
