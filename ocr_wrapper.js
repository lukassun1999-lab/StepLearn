#!/usr/bin/env node
const Tesseract = require('tesseract.js');
const path = require('path');
const fs = require('fs');

const args = process.argv.slice(2);
const imagePath = args.find(a => !a.startsWith('--'));
const langArg = args.find(a => a === '--lang');
const langIdx = langArg ? args.indexOf(langArg) : -1;
const languages = (langIdx >= 0 && args[langIdx + 1]) ? args[langIdx + 1] : 'chi_sim+eng';
const outputJson = args.includes('--json');
const langPath = path.join(__dirname, 'tessdata');

if (!imagePath || !fs.existsSync(imagePath)) {
  console.error('Usage: node ocr_wrapper.js <image> [--lang chi_sim+eng] [--json]');
  process.exit(1);
}

async function recognize() {
  const worker = await Tesseract.createWorker(languages, 1, {
    langPath: langPath,
    logger: m => {
      if (m.status === 'recognizing text') {
        process.stderr.write(`\rProgress: ${Math.round(m.progress * 100)}%`);
      }
    }
  });

  const result = await worker.recognize(imagePath);
  await worker.terminate();

  process.stderr.write('\n');

  if (outputJson) {
    console.log(JSON.stringify({
      text: result.data.text,
      confidence: result.data.confidence,
      words: (result.data.words || []).map(w => ({
        text: w.text,
        confidence: w.confidence,
        bbox: w.bbox
      }))
    }));
  } else {
    console.log(result.data.text);
  }
}

recognize().catch(e => {
  console.error(`Error: ${e.message}`);
  process.exit(1);
});
