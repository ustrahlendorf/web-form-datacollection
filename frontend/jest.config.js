module.exports = {
  testEnvironment: 'jsdom',
  testMatch: ['**/*.test.js', '**/*.pbt.js'],
  collectCoverageFrom: [
    'src/*.js',
    '!**/*.test.js',
    '!**/*.pbt.js',
    '!jest.config.js',
  ],
};
