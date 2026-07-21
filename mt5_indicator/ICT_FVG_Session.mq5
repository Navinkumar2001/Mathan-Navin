//+------------------------------------------------------------------+
//|                                           ICT_FVG_Session.mq5    |
//|                        ICT FVG + Session Indicator                |
//|         Observation: 07:00-15:30 | Trading: 15:30-21:00 (MT5)    |
//+------------------------------------------------------------------+
#property copyright "ICT Trading Bot"
#property version   "1.00"
#property indicator_chart_window
#property indicator_buffers 2
#property indicator_plots   2

//--- Arrow plots
#property indicator_label1  "BUY Signal"
#property indicator_type1   DRAW_ARROW
#property indicator_color1  clrDodgerBlue
#property indicator_width1  3

#property indicator_label2  "SELL Signal"
#property indicator_type2   DRAW_ARROW
#property indicator_color2  clrOrangeRed
#property indicator_width2  3

//--- Input parameters
input int    InpObservationStartHour = 7;     // Observation Start Hour (MT5 server time)
input int    InpObservationStartMin  = 0;     // Observation Start Minute
input int    InpObservationEndHour   = 15;    // Observation End Hour
input int    InpObservationEndMin    = 30;    // Observation End Minute
input int    InpTradingStartHour     = 15;    // Trading Start Hour
input int    InpTradingStartMin      = 30;    // Trading Start Minute
input int    InpTradingEndHour       = 21;    // Trading End Hour
input int    InpTradingEndMin        = 0;     // Trading End Minute
input double InpMinFVGPips           = 2.0;   // Minimum FVG Size (pips)
input double InpMinDisplacementPips  = 10.0;  // Minimum Displacement (pips)
input double InpBodyRatioMin         = 0.6;   // Min Body/Range Ratio for Displacement
input color  InpObsColor             = clrGold;        // Observation Zone Color
input color  InpTradeColor           = clrLimeGreen;   // Trading Zone Color
input color  InpBullFVGColor         = clrDodgerBlue;  // Bullish FVG Color
input color  InpBearFVGColor         = clrOrangeRed;   // Bearish FVG Color
input color  InpSessionHighColor     = clrAqua;        // Session High Line Color
input color  InpSessionLowColor      = clrMagenta;     // Session Low Line Color
input int    InpATRPeriod            = 14;    // ATR Period for SL calculation
input double InpATRMultiplier        = 1.5;   // ATR Multiplier for SL

//--- Buffers
double BuyBuffer[];
double SellBuffer[];

//--- Global variables
double g_pipValue;
datetime g_lastSessionDate;
double g_sessionHigh;
double g_sessionLow;
int g_atrHandle;

//+------------------------------------------------------------------+
//| Custom indicator initialization function                          |
//+------------------------------------------------------------------+
int OnInit()
{
   //--- Set pip value
   if(StringFind(_Symbol, "JPY") >= 0)
      g_pipValue = 0.01;
   else
      g_pipValue = 0.0001;

   //--- Setup buffers
   SetIndexBuffer(0, BuyBuffer, INDICATOR_DATA);
   SetIndexBuffer(1, SellBuffer, INDICATOR_DATA);

   //--- Arrow codes: 233 = up arrow, 234 = down arrow
   PlotIndexSetInteger(0, PLOT_ARROW, 233);
   PlotIndexSetInteger(1, PLOT_ARROW, 234);

   //--- No value
   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, 0.0);
   PlotIndexSetDouble(1, PLOT_EMPTY_VALUE, 0.0);

   //--- ATR handle
   g_atrHandle = iATR(_Symbol, PERIOD_CURRENT, InpATRPeriod);

   g_lastSessionDate = 0;
   g_sessionHigh = 0;
   g_sessionLow = DBL_MAX;

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Custom indicator deinitialization                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, "ICT_");
   if(g_atrHandle != INVALID_HANDLE)
      IndicatorRelease(g_atrHandle);
}

//+------------------------------------------------------------------+
//| Helper: Check if time is in observation session                   |
//+------------------------------------------------------------------+
bool IsObservationSession(datetime time)
{
   MqlDateTime dt;
   TimeToStruct(time, dt);
   int minutes = dt.hour * 60 + dt.min;
   int obsStart = InpObservationStartHour * 60 + InpObservationStartMin;
   int obsEnd = InpObservationEndHour * 60 + InpObservationEndMin;
   return (minutes >= obsStart && minutes < obsEnd);
}

//+------------------------------------------------------------------+
//| Helper: Check if time is in trading session                       |
//+------------------------------------------------------------------+
bool IsTradingSession(datetime time)
{
   MqlDateTime dt;
   TimeToStruct(time, dt);
   int minutes = dt.hour * 60 + dt.min;
   int tradeStart = InpTradingStartHour * 60 + InpTradingStartMin;
   int tradeEnd = InpTradingEndHour * 60 + InpTradingEndMin;
   return (minutes >= tradeStart && minutes < tradeEnd);
}

//+------------------------------------------------------------------+
//| Helper: Get date only from datetime                               |
//+------------------------------------------------------------------+
datetime GetDateOnly(datetime time)
{
   MqlDateTime dt;
   TimeToStruct(time, dt);
   dt.hour = 0;
   dt.min = 0;
   dt.sec = 0;
   return StructToTime(dt);
}

//+------------------------------------------------------------------+
//| Helper: Check if candle is a displacement candle                  |
//+------------------------------------------------------------------+
bool IsDisplacementCandle(double open_price, double high, double low, double close_price)
{
   double body = MathAbs(close_price - open_price);
   double range = high - low;

   if(range <= 0) return false;

   double bodyRatio = body / range;
   if(bodyRatio < InpBodyRatioMin) return false;

   double minDisplacement = InpMinDisplacementPips * g_pipValue;
   if(range < minDisplacement) return false;

   return true;
}

//+------------------------------------------------------------------+
//| Draw session background rectangle                                 |
//+------------------------------------------------------------------+
void DrawSessionZone(datetime timeStart, datetime timeEnd, string prefix, color clr)
{
   string name = "ICT_" + prefix + "_" + TimeToString(timeStart, TIME_DATE|TIME_MINUTES);

   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_RECTANGLE, 0, timeStart, 0, timeEnd, 0);
   }

   // Get chart price range for rectangle height
   double chartHigh = ChartGetDouble(0, CHART_PRICE_MAX);
   double chartLow = ChartGetDouble(0, CHART_PRICE_MIN);

   ObjectSetInteger(0, name, OBJPROP_TIME, 0, timeStart);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 0, chartHigh);
   ObjectSetInteger(0, name, OBJPROP_TIME, 1, timeEnd);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 1, chartLow);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DOT);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_FILL, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   // Semi-transparent
   ObjectSetInteger(0, name, OBJPROP_COLOR, ColorToARGB(clr, 30));
}

//+------------------------------------------------------------------+
//| Draw session high/low horizontal lines                            |
//+------------------------------------------------------------------+
void DrawSessionHighLow(datetime timeStart, datetime timeEnd, double highPrice, double lowPrice)
{
   string nameHigh = "ICT_SessHigh_" + TimeToString(timeStart, TIME_DATE);
   string nameLow = "ICT_SessLow_" + TimeToString(timeStart, TIME_DATE);
   string nameMid = "ICT_SessMid_" + TimeToString(timeStart, TIME_DATE);

   double midPrice = (highPrice + lowPrice) / 2.0;

   // Session High line
   if(ObjectFind(0, nameHigh) < 0)
      ObjectCreate(0, nameHigh, OBJ_TREND, 0, timeStart, highPrice, timeEnd, highPrice);
   ObjectSetDouble(0, nameHigh, OBJPROP_PRICE, 0, highPrice);
   ObjectSetDouble(0, nameHigh, OBJPROP_PRICE, 1, highPrice);
   ObjectSetInteger(0, nameHigh, OBJPROP_TIME, 0, timeStart);
   ObjectSetInteger(0, nameHigh, OBJPROP_TIME, 1, timeEnd);
   ObjectSetInteger(0, nameHigh, OBJPROP_COLOR, InpSessionHighColor);
   ObjectSetInteger(0, nameHigh, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, nameHigh, OBJPROP_WIDTH, 2);
   ObjectSetInteger(0, nameHigh, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, nameHigh, OBJPROP_BACK, false);
   ObjectSetString(0, nameHigh, OBJPROP_TEXT, "Session High: " + DoubleToString(highPrice, _Digits));

   // Session Low line
   if(ObjectFind(0, nameLow) < 0)
      ObjectCreate(0, nameLow, OBJ_TREND, 0, timeStart, lowPrice, timeEnd, lowPrice);
   ObjectSetDouble(0, nameLow, OBJPROP_PRICE, 0, lowPrice);
   ObjectSetDouble(0, nameLow, OBJPROP_PRICE, 1, lowPrice);
   ObjectSetInteger(0, nameLow, OBJPROP_TIME, 0, timeStart);
   ObjectSetInteger(0, nameLow, OBJPROP_TIME, 1, timeEnd);
   ObjectSetInteger(0, nameLow, OBJPROP_COLOR, InpSessionLowColor);
   ObjectSetInteger(0, nameLow, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, nameLow, OBJPROP_WIDTH, 2);
   ObjectSetInteger(0, nameLow, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, nameLow, OBJPROP_BACK, false);
   ObjectSetString(0, nameLow, OBJPROP_TEXT, "Session Low: " + DoubleToString(lowPrice, _Digits));

   // Midpoint line
   if(ObjectFind(0, nameMid) < 0)
      ObjectCreate(0, nameMid, OBJ_TREND, 0, timeStart, midPrice, timeEnd, midPrice);
   ObjectSetDouble(0, nameMid, OBJPROP_PRICE, 0, midPrice);
   ObjectSetDouble(0, nameMid, OBJPROP_PRICE, 1, midPrice);
   ObjectSetInteger(0, nameMid, OBJPROP_TIME, 0, timeStart);
   ObjectSetInteger(0, nameMid, OBJPROP_TIME, 1, timeEnd);
   ObjectSetInteger(0, nameMid, OBJPROP_COLOR, clrWhite);
   ObjectSetInteger(0, nameMid, OBJPROP_STYLE, STYLE_DOT);
   ObjectSetInteger(0, nameMid, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, nameMid, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, nameMid, OBJPROP_BACK, false);
   ObjectSetString(0, nameMid, OBJPROP_TEXT, "Midpoint: " + DoubleToString(midPrice, _Digits));
}

//+------------------------------------------------------------------+
//| Draw FVG rectangle on chart                                       |
//+------------------------------------------------------------------+
void DrawFVG(datetime time1, datetime time2, double top, double bottom, bool isBullish, int idx)
{
   string dir = isBullish ? "Bull" : "Bear";
   string name = "ICT_FVG_" + dir + "_" + IntegerToString(idx);

   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_RECTANGLE, 0, time1, top, time2, bottom);

   ObjectSetInteger(0, name, OBJPROP_TIME, 0, time1);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 0, top);
   ObjectSetInteger(0, name, OBJPROP_TIME, 1, time2);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 1, bottom);
   ObjectSetInteger(0, name, OBJPROP_COLOR, isBullish ? InpBullFVGColor : InpBearFVGColor);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_SOLID);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_FILL, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);

   // Label
   string labelName = "ICT_FVG_Lbl_" + dir + "_" + IntegerToString(idx);
   if(ObjectFind(0, labelName) < 0)
      ObjectCreate(0, labelName, OBJ_TEXT, 0, time2, (top + bottom) / 2.0);
   ObjectSetInteger(0, labelName, OBJPROP_TIME, 0, time2);
   ObjectSetDouble(0, labelName, OBJPROP_PRICE, 0, (top + bottom) / 2.0);
   ObjectSetString(0, labelName, OBJPROP_TEXT, isBullish ? "FVG BUY" : "FVG SELL");
   ObjectSetInteger(0, labelName, OBJPROP_COLOR, isBullish ? InpBullFVGColor : InpBearFVGColor);
   ObjectSetInteger(0, labelName, OBJPROP_FONTSIZE, 8);
}

//+------------------------------------------------------------------+
//| Draw ATR-based Stop Loss line                                     |
//+------------------------------------------------------------------+
void DrawSLLine(datetime time1, datetime time2, double slPrice, bool isBuy, int idx)
{
   string name = "ICT_SL_" + IntegerToString(idx);

   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TREND, 0, time1, slPrice, time2, slPrice);

   ObjectSetDouble(0, name, OBJPROP_PRICE, 0, slPrice);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 1, slPrice);
   ObjectSetInteger(0, name, OBJPROP_TIME, 0, time1);
   ObjectSetInteger(0, name, OBJPROP_TIME, 1, time2);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clrRed);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DASHDOT);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetString(0, name, OBJPROP_TEXT, "SL (ATR): " + DoubleToString(slPrice, _Digits));
}

//+------------------------------------------------------------------+
//| Custom indicator iteration function                               |
//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   if(rates_total < 3) return 0;

   //--- ATR buffer
   double atrBuffer[];
   ArraySetAsSeries(atrBuffer, true);
   if(CopyBuffer(g_atrHandle, 0, 0, rates_total, atrBuffer) <= 0)
      return prev_calculated;

   //--- Set arrays as series (most recent = index 0 for ATR)
   //--- But main arrays are NOT series (index 0 = oldest)

   int start = (prev_calculated < 3) ? 2 : prev_calculated - 1;

   for(int i = start; i < rates_total; i++)
   {
      BuyBuffer[i] = 0.0;
      SellBuffer[i] = 0.0;

      datetime barTime = time[i];
      datetime barDate = GetDateOnly(barTime);

      //--- Draw session zones (once per day)
      if(barDate != g_lastSessionDate && i > 0)
      {
         g_lastSessionDate = barDate;

         // Reset session high/low for new day
         g_sessionHigh = 0;
         g_sessionLow = DBL_MAX;

         // Build observation zone times
         MqlDateTime dtObs;
         TimeToStruct(barDate, dtObs);
         dtObs.hour = InpObservationStartHour;
         dtObs.min = InpObservationStartMin;
         datetime obsStart = StructToTime(dtObs);
         dtObs.hour = InpObservationEndHour;
         dtObs.min = InpObservationEndMin;
         datetime obsEnd = StructToTime(dtObs);

         // Build trading zone times
         MqlDateTime dtTrd;
         TimeToStruct(barDate, dtTrd);
         dtTrd.hour = InpTradingStartHour;
         dtTrd.min = InpTradingStartMin;
         datetime trdStart = StructToTime(dtTrd);
         dtTrd.hour = InpTradingEndHour;
         dtTrd.min = InpTradingEndMin;
         datetime trdEnd = StructToTime(dtTrd);

         DrawSessionZone(obsStart, obsEnd, "OBS", InpObsColor);
         DrawSessionZone(trdStart, trdEnd, "TRD", InpTradeColor);
      }

      //--- Track session high/low during observation
      if(IsObservationSession(barTime))
      {
         if(high[i] > g_sessionHigh) g_sessionHigh = high[i];
         if(low[i] < g_sessionLow) g_sessionLow = low[i];

         // Draw/update session lines extending into trading session
         if(g_sessionHigh > 0 && g_sessionLow < DBL_MAX)
         {
            MqlDateTime dtEnd;
            TimeToStruct(barDate, dtEnd);
            dtEnd.hour = InpTradingEndHour;
            dtEnd.min = InpTradingEndMin;
            datetime lineEnd = StructToTime(dtEnd);

            MqlDateTime dtStart;
            TimeToStruct(barDate, dtStart);
            dtStart.hour = InpObservationStartHour;
            dtStart.min = InpObservationStartMin;
            datetime lineStart = StructToTime(dtStart);

            DrawSessionHighLow(lineStart, lineEnd, g_sessionHigh, g_sessionLow);
         }
      }

      //--- FVG Detection: need at least 3 candles
      if(i < 2) continue;

      // Candle indices: c1 = i-2, c2 = i-1 (displacement), c3 = i
      int c1 = i - 2;
      int c2 = i - 1;
      int c3 = i;

      // Check if middle candle is displacement
      if(!IsDisplacementCandle(open[c2], high[c2], low[c2], close[c2]))
         continue;

      double minFVGSize = InpMinFVGPips * g_pipValue;

      //--- Bullish FVG: c1 high < c3 low (gap up)
      if(high[c1] < low[c3])
      {
         double fvgSize = low[c3] - high[c1];
         if(fvgSize < minFVGSize) continue;

         // Confirmation: c2 must be bullish
         if(close[c2] <= open[c2]) continue;
         // Confirmation: c3 must close above FVG bottom and be bullish
         if(close[c3] <= high[c1]) continue;
         if(close[c3] < open[c3]) continue;

         // Only signal during trading session
         if(IsTradingSession(barTime))
         {
            // Place buy arrow below the FVG
            BuyBuffer[i] = low[c3] - (5 * g_pipValue);

            // Draw FVG zone
            DrawFVG(time[c1], time[c3], low[c3], high[c1], true, i);

            // Draw ATR stop loss
            int atrIdx = rates_total - 1 - i;  // Convert to series index
            if(atrIdx >= 0 && atrIdx < ArraySize(atrBuffer))
            {
               double atr = atrBuffer[atrIdx];
               double slDistance = MathMax(atr * InpATRMultiplier, 10 * g_pipValue);
               double slPrice = close[c3] - slDistance;
               DrawSLLine(time[c2], time[c3] + PeriodSeconds() * 5, slPrice, true, i);
            }
         }
         else if(IsObservationSession(barTime))
         {
            // During observation, just draw the FVG zone (no signal)
            DrawFVG(time[c1], time[c3], low[c3], high[c1], true, i);
         }
      }
      //--- Bearish FVG: c1 low > c3 high (gap down)
      else if(low[c1] > high[c3])
      {
         double fvgSize = low[c1] - high[c3];
         if(fvgSize < minFVGSize) continue;

         // Confirmation: c2 must be bearish
         if(close[c2] >= open[c2]) continue;
         // Confirmation: c3 must close below FVG top and be bearish
         if(close[c3] >= low[c1]) continue;
         if(close[c3] > open[c3]) continue;

         // Only signal during trading session
         if(IsTradingSession(barTime))
         {
            // Place sell arrow above the FVG
            SellBuffer[i] = high[c3] + (5 * g_pipValue);

            // Draw FVG zone
            DrawFVG(time[c1], time[c3], low[c1], high[c3], false, i);

            // Draw ATR stop loss
            int atrIdx = rates_total - 1 - i;
            if(atrIdx >= 0 && atrIdx < ArraySize(atrBuffer))
            {
               double atr = atrBuffer[atrIdx];
               double slDistance = MathMax(atr * InpATRMultiplier, 10 * g_pipValue);
               double slPrice = close[c3] + slDistance;
               DrawSLLine(time[c2], time[c3] + PeriodSeconds() * 5, slPrice, false, i);
            }
         }
         else if(IsObservationSession(barTime))
         {
            // During observation, just draw the FVG zone (no signal)
            DrawFVG(time[c1], time[c3], low[c1], high[c3], false, i);
         }
      }
   }

   return rates_total;
}
//+------------------------------------------------------------------+
