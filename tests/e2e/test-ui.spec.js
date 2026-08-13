import { test, expect } from '@playwright/test';

test('UI loads and initializes correctly', async ({ page }) => {
  await page.goto('http://localhost:8000');
  await page.waitForLoadState('networkidle');
  
  // Check that the title is present
  await expect(page.locator('.app-title')).toHaveText('Personal Cashflow Dashboard');
  
  // Check scenario badge loads (not "Loading...")
  await expect(page.locator('#scenarioBadge')).not.toHaveText('Loading...');
  
  // Check left panel parameters load
  await expect(page.locator('#parametersList')).not.toBeEmpty();
  
  // Check charts render
  await expect(page.locator('#netWorthChart')).toBeVisible();
  await expect(page.locator('#cashFlowChart')).toBeVisible();
  
  // Check console for JavaScript errors
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') {
      errors.push(msg.text());
    }
  });
  page.on('pageerror', error => {
    errors.push(error.message);
  });
  
  // Wait a bit for any async errors
  await page.waitForTimeout(2000);
  
  console.log('Console errors:', errors);
  
  // Should have no syntax errors
  const syntaxErrors = errors.filter(e => e.includes('SyntaxError') || e.includes('Unexpected'));
  expect(syntaxErrors).toHaveLength(0);
  
  // Favicon should load without 404
  const faviconResponse = await page.request.get('http://localhost:8000/static/favicon.ico');
  expect(faviconResponse.ok()).toBeTruthy();
  
  // Take screenshot for verification
  await page.screenshot({ path: '/tmp/ui-test.png', fullPage: true });
});
