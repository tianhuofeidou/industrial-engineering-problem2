// 只将同目录SVG栅格化，不连接网络，不创建演示文稿。
const fs = require('fs');
const path = require('path');
const sharp = require(require.resolve('sharp', {paths: [process.env.CODEX_NODE_MODULES, __dirname].filter(Boolean)}));
const dir = path.resolve(__dirname, '../图片');
(async () => {
  for (const name of fs.readdirSync(dir).filter(n => n.endsWith('.svg'))) {
    await sharp(path.join(dir, name), {density: 144}).png().toFile(path.join(dir, name.replace(/\.svg$/, '.png')));
    process.stdout.write(name + '\n');
  }
})().catch(e => {process.stderr.write(String(e)); process.exitCode = 1;});
