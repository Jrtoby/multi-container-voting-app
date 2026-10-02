FROM node:20-alpine

WORKDIR /worker

COPY package*.json ./

RUN npm ci

COPY . .

CMD ["node", "worker.js"]