const { chromium } = require('playwright');
// node tela.js <pasta-de-saída>  (servidor_tela.py no ar na porta 8777, banco recém-carregado)
const fs = require('fs');
const S = process.argv[2] || '.', BASE = 'http://127.0.0.1:8777/';
fs.mkdirSync(S + '/shots', { recursive: true }); fs.mkdirSync(S + '/upl', { recursive: true });
fs.writeFileSync(S + '/upl/pedido.png', Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from('pedido-' + Date.now())]));
fs.writeFileSync(S + '/upl/pix.pdf', '%PDF-1.7\npix-' + Date.now());
const erros = [];
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 680, height: 1000 }, deviceScaleFactor: 1 });
  const p = await ctx.newPage();
  p.on('console', m => { if (m.type() === 'error' && !/fonts\.(googleapis|gstatic)|status of 401/.test(m.text())) erros.push('console: ' + m.text()); });
  p.on('pageerror', e => erros.push('pageerror: ' + e.message));
  const passo = (t) => console.log('✓ ' + t);
  const semRolagemLateral = async (rot) => {
    const w = await p.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    if (w[0] > w[1]) erros.push(`${rot}: página rola para o lado (${w[0]} > ${w[1]})`);
  };

  await p.goto(BASE);
  await p.fill('#e-email', 'dono@teste.invalid'); await p.fill('#e-senha', 'errada'); await p.click('button[type=submit]');
  await p.waitForSelector('.erro'); passo('senha errada: ' + await p.textContent('.erro'));
  await p.fill('#e-email', 'dono@teste.invalid'); await p.fill('#e-senha', 'senha-de-teste-123'); await p.click('button[type=submit]');
  await p.waitForSelector('.kpi.lead');
  passo('painel: caixa ' + await p.textContent('.kpi.lead .num'));
  await semRolagemLateral('painel 680');
  // três cartões menores lado a lado em 680px
  const tops = await p.$$eval('.kpi:not(.lead)', els => els.map(e => Math.round(e.getBoundingClientRect().top)));
  if (new Set(tops).size !== 1) erros.push('cartões menores não estão lado a lado: ' + tops);
  await p.screenshot({ path: S + '/shots/painel-680.png', fullPage: true });

  // resultado por mês: seta, lista e barra
  await p.click('[data-act=mes-nav][data-d="-1"]');
  const sel1 = await p.$eval('#mes-sel', e => e.value);
  await p.selectOption('#mes-sel', '2026-10'); await p.click('.col[data-m="2026-09"]');
  passo(`mês: seta→${sel1}, barra→${await p.$eval('#mes-sel', e => e.value)}, deixou de ganhar ${await p.textContent('.stat .perdeu')}`);

  // busca filtra sem perder o foco
  await p.click('#busca'); await p.keyboard.type('brislu');
  const foco = await p.evaluate(() => document.activeElement.id);
  passo(`busca "brislu": ${await p.textContent('#conta-ops')}, foco em #${foco}`);
  if (foco !== 'busca') erros.push('busca perdeu o foco');
  await p.fill('#busca', ''); await p.dispatchEvent('#busca', 'input');

  // nova operação: caixa insuficiente, depois certo
  await p.click('[data-act=nova-op]');
  await p.selectOption('#f-forn', '2');
  passo('aviso do fornecedor: ' + (await p.textContent('#f-aviso-forn')).slice(0, 40) + '…');
  await p.fill('#f-pago', '200.000,00'); await p.fill('#f-cheio', '210000'); await p.click('[data-p-act=dividir]');
  await p.fill('#f-ped', 'PC 03700-1/26');
  await p.click('[data-act=confirmar]'); await p.waitForSelector('.modal .erro');
  passo('caixa insuficiente: ' + await p.textContent('.modal .erro'));
  await p.fill('#f-pago', '4.107,84'); await p.fill('#f-cheio', '4279,00'); await p.click('[data-p-act=dividir]');
  passo('prévia: ' + (await p.textContent('#f-previa')).replace(/\s+/g, ' ') + ' | ' + (await p.textContent('#parc-soma')));
  await p.$$eval('#parc-edit input[data-p=v]', (els) => { els[1].value = '2000,00'; els[1].dispatchEvent(new Event('input', { bubbles: true })); });
  passo('soma errada fica vermelha: ' + await p.$eval('#parc-soma', e => e.className));
  await p.click('[data-p-act=dividir]');
  await p.screenshot({ path: S + '/shots/form-680.png' });
  await p.focus('#f-obs'); await p.keyboard.press('Enter');   // Enter num campo confirma
  await p.waitForSelector('.modal', { state: 'detached' });
  await p.waitForFunction(() => document.getElementById('status-chip').textContent === 'Tudo salvo');
  passo('lançada: caixa ' + await p.textContent('.kpi.lead .num') + ' · ' + await p.textContent('#conta-ops'));

  // receber a duplicata da op 7 (PC 03273-2/26)
  const chip = p.locator('tr', { hasText: 'PC 03273-2/26' }).locator('.pchip').first();
  passo('aria-label da duplicata: ' + await chip.getAttribute('aria-label'));
  await chip.click(); await p.click('[data-act=confirmar]');
  await p.waitForSelector('.modal', { state: 'detached' });
  await p.waitForFunction(() => document.getElementById('status-chip').textContent === 'Tudo salvo');
  passo('recebida: ' + await p.locator('tr', { hasText: 'PC 03273-2/26' }).locator('.chip').first().textContent() + ' · caixa ' + await p.textContent('.kpi.lead .num'));
  // Esc fecha; clique fora fecha
  await p.locator('tr', { hasText: 'PC 03273-2/26' }).locator('.pchip').first().click();
  passo('recebida abre: ' + await p.textContent('.modal-head h3')); await p.keyboard.press('Escape');
  if (await p.$('.modal')) erros.push('Esc não fechou');

  // robô: enviar pedido + PIX → A conferir → usar itens → aprovar
  await p.click('[data-act=enviar-docs]');
  await p.setInputFiles('#f-arqs', [S + '/upl/pedido.png', S + '/upl/pix.pdf']);
  await p.click('[data-act=confirmar]');
  await p.waitForSelector('.pend-card');
  passo('A conferir: ' + (await p.textContent('.pend-card .pend ul')).slice(0, 90) + '…');
  await p.screenshot({ path: S + '/shots/conferir-680.png', fullPage: false, clip: await p.$eval('.pend-card', e => { const r = e.getBoundingClientRect(); return { x: 0, y: r.top + window.scrollY, width: 680, height: r.height }; }) }).catch(() => {});
  await p.click('[data-act=r-cheio]:has-text("Usar itens")');
  await p.waitForSelector('[data-act=r-aprovar]');
  await p.click('[data-act=r-aprovar]'); await p.click('[data-act=confirmar]');
  await p.waitForSelector('.pend-card', { state: 'detached' });
  passo('rascunho aprovado; card A conferir sumiu; linha: ' + (await p.locator('tr', { hasText: 'PC 03610-1/26' }).locator('.num.lucro').textContent()));

  // estorno de operação com recebimento exige motivo
  await p.locator('tr', { hasText: 'PC 03282-4/26' }).locator('[data-act=excluir-op]').click();
  await p.click('[data-act=confirmar]'); await p.waitForSelector('.modal .erro');
  passo('estorno sem motivo: ' + await p.textContent('.modal .erro'));
  await p.keyboard.press('Escape');

  // aporte e retirada grande demais
  await p.click('[data-act=mov][data-tipo=retirada]'); await p.fill('#f-valor', '999.999,00'); await p.click('[data-act=confirmar]');
  passo('retirada grande: ' + await p.textContent('.modal .erro')); await p.keyboard.press('Escape');

  // tema escuro e desktop
  await p.emulateMedia({ colorScheme: 'dark' });
  await p.screenshot({ path: S + '/shots/painel-680-escuro.png', fullPage: false });
  await p.setViewportSize({ width: 1240, height: 900 }); await p.emulateMedia({ colorScheme: 'light' });
  await semRolagemLateral('painel 1240');
  await p.screenshot({ path: S + '/shots/painel-1240.png', fullPage: false });
  await p.setViewportSize({ width: 375, height: 800 }); await semRolagemLateral('painel 375');

  // outras telas
  await p.setViewportSize({ width: 680, height: 900 });
  await p.goto(BASE + '#/fornecedores'); await p.waitForSelector('table');
  passo('fornecedores: ' + await p.$$eval('tbody tr', r => r.length) + ' linhas');
  await p.goto(BASE + '#/historico'); await p.waitForSelector('#hist-body tr td.num');
  passo('histórico: ' + await p.$$eval('#hist-body tr', r => r.length) + ' eventos; 1º: ' + (await p.textContent('#hist-body tr')).replace(/\s+/g, ' ').slice(0, 80));
  await p.screenshot({ path: S + '/shots/historico-680.png' });
  await semRolagemLateral('histórico 680');

  console.log(erros.length ? '\nPROBLEMAS:\n' + erros.join('\n') : '\nsem erros de console, sem rolagem lateral');
  await b.close();
})().catch(e => { console.error('FALHOU:', e.message); console.log(erros.join('\n')); process.exit(1); });
