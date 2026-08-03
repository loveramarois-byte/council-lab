declare module "lunar-javascript" {
  type EightChar = {
    toString(): string;
    getYear(): string;
    getMonth(): string;
    getDay(): string;
    getTime(): string;
    getYearWuXing(): string;
    getMonthWuXing(): string;
    getDayWuXing(): string;
    getTimeWuXing(): string;
    getYearShiShenGan(): string;
    getMonthShiShenGan(): string;
    getDayShiShenGan(): string;
    getTimeShiShenGan(): string;
  };

  type LunarDate = {
    toString(): string;
    getYearShengXiao(): string;
    getEightChar(): EightChar;
    getJieQi(): string;
    getPrevJieQi(): SolarTerm;
    getNextJieQi(): SolarTerm;
  };

  type SolarTerm = {
    getName(): string;
    getSolar(): SolarDate;
  };

  type SolarDate = {
    toYmdHms(): string;
    getXingZuo(): string;
    getLunar(): LunarDate;
  };

  export const Solar: {
    fromYmdHms(year: number, month: number, day: number, hour: number, minute: number, second: number): SolarDate;
  };
}
