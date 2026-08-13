import { test, expect } from '@playwright/test';

test('Parameter interactions work correctly', async ({ page }) => {
  await page.goto('http://localhost:8000');
  await page.waitForLoadState('networkidle');

  // Select generic-demo explicitly so this test does not depend on scenario
  // glob order or the default scenario.
  const scenarioSelect = page.locator('#scenarioSelect');
  await scenarioSelect.waitFor({ state: 'visible' });
  await page.waitForFunction(() => {
    const sel = document.getElementById('scenarioSelect');
    return sel && sel.options.length > 0;
  });
  await scenarioSelect.selectOption('generic-demo');

  // Wait for generic-demo's parameters to finish loading (networkidle covers
  // the in-flight /parameters fetch) so the category expansion below targets
  // the final DOM instead of the default scenario's stale one.
  await page.waitForLoadState('networkidle');

  // Wait for parameters to load
  await page.waitForSelector('#parametersList .param-category', { timeout: 10000 });

  // Expand all categories. Scenario switching re-renders the parameter list
  // (categories start collapsed), so keep clicking until none remain.
  for (let attempt = 0; attempt < 10; attempt++) {
    const categoryHeaders = page.locator('.param-category-header');
    const count = await categoryHeaders.count();
    for (let i = 0; i < count; i++) {
      const header = categoryHeaders.nth(i);
      const isCollapsed = await header.locator('..').evaluate(el => el.classList.contains('collapsed'));
      if (isCollapsed) {
        await header.click();
      }
    }
    const stillCollapsed = await page.locator('.param-category.collapsed').count();
    if (stillCollapsed === 0) break;
    await page.waitForTimeout(200);
  }

  // Test 1: Life Decision toggle from .variable_meta (social security)
  const ssToggle = page.locator('input[data-path="variables.social_security_enabled"]');
  await expect(ssToggle).toBeVisible();
  const initialSs = await ssToggle.isChecked();
  await ssToggle.click();
  await page.waitForTimeout(500);
  const afterSs = await ssToggle.isChecked();
  expect(afterSs).not.toBe(initialSs);
  console.log('✓ Life Decision toggle (social_security_enabled) works');

  // Test 2: Primary salary base_amount (text input)
  const salaryBaseAmount = page.locator('input[data-path="events.primary_salary.base_amount"]');
  await expect(salaryBaseAmount).toBeVisible();
  await salaryBaseAmount.fill('150000');
  await page.waitForTimeout(500);
  expect(await salaryBaseAmount.inputValue()).toBe('150000');
  console.log('✓ Primary salary base_amount input works');

  // Test 3: Gap years textarea
  const salaryGapYears = page.locator('textarea[data-path="events.primary_salary.gap_years"]');
  await expect(salaryGapYears).toBeVisible();
  await salaryGapYears.fill('2027, 2028');
  await page.waitForTimeout(500);
  expect(await salaryGapYears.inputValue()).toContain('2027');
  console.log('✓ Primary salary gap_years input works');

  // Test 4: Asset purchase parameters
  const downPayment = page.locator('input[data-path="events.primary_residence_acquisition.down_payment"]');
  await expect(downPayment).toBeVisible();
  await downPayment.fill('120000');
  await page.waitForTimeout(500);
  expect(await downPayment.inputValue()).toBe('120000');
  console.log('✓ Asset down_payment input works');

  const assetValue = page.locator('input[data-path="events.primary_residence_acquisition.asset_initial_value"]');
  await expect(assetValue).toBeVisible();
  await assetValue.fill('450000');
  await page.waitForTimeout(500);
  expect(await assetValue.inputValue()).toBe('450000');
  console.log('✓ Asset asset_initial_value input works');

  const mortgageRate = page.locator('input[data-path="events.primary_residence_acquisition.mortgage.interest_rate"]');
  await expect(mortgageRate).toBeVisible();
  await mortgageRate.fill('0.06');
  await page.waitForTimeout(500);
  expect(await mortgageRate.inputValue()).toBe('0.06');
  console.log('✓ Mortgage interest_rate input works');

  // Test 5: Step adjustments table editor
  const stepAdjustmentAdd = page.locator('.step-adjustment-add[data-event-id="primary_salary"]');
  await expect(stepAdjustmentAdd).toBeVisible();
  await stepAdjustmentAdd.click();
  await page.waitForTimeout(500);

  const newYearInput = page.locator('.step-adjustments-rows[data-event-id="primary_salary"] .step-adjustment-year').last();
  const newValueInput = page.locator('.step-adjustments-rows[data-event-id="primary_salary"] .step-adjustment-value').last();

  await newYearInput.fill('2028');
  await newValueInput.fill('1.12');
  await page.waitForTimeout(500);

  expect(await newYearInput.inputValue()).toBe('2028');
  expect(await newValueInput.inputValue()).toBe('1.12');
  console.log('✓ Step adjustments editor works');

  // Test 6: Run simulation with changes
  const runBtn = page.locator('#runSimulationBtn');
  await runBtn.click();

  // Wait for simulation to complete
  await page.waitForFunction(() => {
    const btn = document.getElementById('runSimulationBtn');
    return btn && !btn.disabled && btn.textContent.includes('Run Simulation');
  }, { timeout: 30000 });

  console.log('✓ Simulation runs successfully');

  // Check for console errors
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') {
      errors.push(msg.text());
    }
  });
  page.on('pageerror', error => {
    errors.push(error.message);
  });

  await page.waitForTimeout(1000);
  console.log('Console errors:', errors);
  const syntaxErrors = errors.filter(e => e.includes('SyntaxError') || e.includes('Unexpected'));
  expect(syntaxErrors).toHaveLength(0);
});
