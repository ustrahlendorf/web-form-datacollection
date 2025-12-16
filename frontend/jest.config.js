module.exports = {
  testEnvironment: 'jsdom',
  testMatch: ['**/*.test.js', '**/*.pbt.js'],
  collectCoverageFrom: ['*.js', '!*.test.js', '!*.pbt.js', '!jest.config.js'],
};
