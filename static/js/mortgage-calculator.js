// Калькулятор ипотеки
class MortgageCalculator {
    constructor() {
        this.currentProgram = 'family';
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.switchProgram('family');
    }

    setupEventListeners() {
        document.querySelectorAll('.mortgage-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                this.switchProgram(e.currentTarget.dataset.program);
            });
        });

        ['property-price', 'down-payment', 'loan-term'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('input', () => this.calculate());
        });

        ['interest-rate', 'family-rate'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('input', () => this.calculate());
        });
    }

    switchProgram(program) {
        this.currentProgram = program;

        document.querySelectorAll('.mortgage-tab').forEach(tab => {
            tab.classList.remove('active-tab', 'text-slate-800');
            tab.classList.add('text-slate-500');
        });
        const activeTab = document.querySelector(`[data-program="${program}"]`);
        if (activeTab) {
            activeTab.classList.remove('text-slate-500');
            activeTab.classList.add('active-tab', 'text-slate-800');
        }

        document.querySelectorAll('.mortgage-result').forEach(r => r.classList.remove('active'));
        const resultEl = document.getElementById(`${program}-result`);
        if (resultEl) resultEl.classList.add('active');

        this.setupRateSlider(program);
        this.calculate();
    }

    setupRateSlider(program) {
        const rateBlock = document.getElementById('interest-rate-block');
        const familyRateBlock = document.getElementById('family-rate-block');
        const rateSlider = document.getElementById('interest-rate');
        const rateDisplay = document.getElementById('rate-display');
        const rateMin = document.getElementById('rate-min');
        const rateMax = document.getElementById('rate-max');

        if (program === 'family') {
            if (rateBlock) rateBlock.classList.add('hidden');
            if (familyRateBlock) familyRateBlock.classList.remove('hidden');
        } else {
            if (rateBlock) rateBlock.classList.remove('hidden');
            if (familyRateBlock) familyRateBlock.classList.add('hidden');
            if (program === 'basic') {
                if (rateSlider) { rateSlider.min = 9; rateSlider.max = 20; rateSlider.value = 16; }
                if (rateMin) rateMin.textContent = '9%';
                if (rateMax) rateMax.textContent = '20%';
                if (rateDisplay) rateDisplay.textContent = '16%';
            } else if (program === 'it') {
                if (rateSlider) { rateSlider.min = 3.5; rateSlider.max = 6; rateSlider.value = 6; }
                if (rateMin) rateMin.textContent = '3.5%';
                if (rateMax) rateMax.textContent = '6%';
                if (rateDisplay) rateDisplay.textContent = '6%';
            }
        }
    }

    getRate() {
        if (this.currentProgram === 'family') {
            const el = document.getElementById('family-rate');
            return el ? parseFloat(el.value) : 6;
        }
        const el = document.getElementById('interest-rate');
        return el ? parseFloat(el.value) : 16;
    }

    calculate() {
        const priceEl = document.getElementById('property-price');
        const dpEl = document.getElementById('down-payment');
        const termEl = document.getElementById('loan-term');
        if (!priceEl || !dpEl || !termEl) return;

        const propertyPrice = parseFloat(priceEl.value);
        let downPaymentPercent = parseFloat(dpEl.value);
        const loanTermYears = parseFloat(termEl.value);
        const interestRate = this.getRate();

        let maxLoanAmount;
        if (this.currentProgram === 'family') {
            maxLoanAmount = 6000000;
            const rateEl = document.getElementById('family-rate');
            const rateDisp = document.getElementById('family-rate-display');
            if (rateEl && rateDisp) rateDisp.textContent = parseFloat(rateEl.value).toFixed(1) + '%';
        } else if (this.currentProgram === 'basic') {
            maxLoanAmount = 15000000;
            const rateEl = document.getElementById('interest-rate');
            const rateDisp = document.getElementById('rate-display');
            if (rateEl && rateDisp) rateDisp.textContent = parseFloat(rateEl.value) + '%';
        } else {
            maxLoanAmount = 9000000;
            const rateEl = document.getElementById('interest-rate');
            const rateDisp = document.getElementById('rate-display');
            if (rateEl && rateDisp) rateDisp.textContent = parseFloat(rateEl.value).toFixed(1) + '%';
        }

        let actualLoanAmount = propertyPrice * (1 - downPaymentPercent / 100);
        let actualDownPaymentPercent = downPaymentPercent;
        let actualDownPaymentAmount = propertyPrice * downPaymentPercent / 100;

        if (actualLoanAmount > maxLoanAmount) {
            actualLoanAmount = maxLoanAmount;
            actualDownPaymentAmount = propertyPrice - actualLoanAmount;
            actualDownPaymentPercent = Math.round((actualDownPaymentAmount / propertyPrice) * 100);
            dpEl.value = actualDownPaymentPercent;
        }

        const priceDisp = document.getElementById('price-display');
        const dpDisp = document.getElementById('down-payment-display');
        const termDisp = document.getElementById('term-display');
        if (priceDisp) priceDisp.textContent = this.formatPrice(propertyPrice) + ' ₽';
        if (dpDisp) dpDisp.textContent = `${actualDownPaymentPercent}% (${this.formatPrice(actualDownPaymentAmount)} ₽)`;
        if (termDisp) termDisp.textContent = `${loanTermYears} лет`;

        const monthlyRate = interestRate / 100 / 12;
        const totalMonths = loanTermYears * 12;
        let monthlyPayment;
        if (monthlyRate === 0) {
            monthlyPayment = actualLoanAmount / totalMonths;
        } else {
            monthlyPayment = actualLoanAmount * (monthlyRate * Math.pow(1 + monthlyRate, totalMonths)) / (Math.pow(1 + monthlyRate, totalMonths) - 1);
        }
        const totalPayment = monthlyPayment * totalMonths;
        const overpayment = totalPayment - actualLoanAmount;

        const prog = this.currentProgram;
        const monthly = document.getElementById(`${prog}-monthly`);
        const overpay = document.getElementById(`${prog}-overpay`);
        const total = document.getElementById(`${prog}-total`);
        if (monthly) monthly.textContent = this.formatPrice(monthlyPayment) + ' ₽';
        if (overpay) overpay.textContent = this.formatPrice(overpayment) + ' ₽';
        if (total) total.textContent = this.formatPrice(totalPayment) + ' ₽';
    }

    formatPrice(price) {
        return Math.round(price).toLocaleString('ru-RU').replace(/,/g, ' ');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new MortgageCalculator();
});
